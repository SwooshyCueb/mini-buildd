# -*- coding: utf-8 -*-
"""
.. graphviz::

  digraph flow_simple
  {
    subgraph cluster_0
    {
      style=filled;
      color=lightgrey;
      label="mini-buildd";
      "Packager";
      "Repository";
    }
    subgraph cluster_1
    {
      style=filled;
      color=lightgrey;
      label="mini-buildd";
      "Builder";
      label = "mini-buildd";
    }
    "Developer" -> "Packager" [label="Upload source package"];
    "Packager" -> "Builder" [label="Build request amd64"];
    "Packager" -> "Builder" [label="Build request i386"];
    "Builder" -> "Packager" [label="Build result amd64"];
    "Builder" -> "Packager" [label="Build result i386"];
    "Packager" -> "Repository" [label="install(amd64, i386)"];
    "Repository" -> "User" [label="apt"];
  }
"""
from __future__ import unicode_literals

import os
import Queue
import collections
import email.mime.text
import email.utils
import logging

import mini_buildd.misc
import mini_buildd.changes
import mini_buildd.gnupg
import mini_buildd.ftpd
import mini_buildd.packager
import mini_buildd.builder

import mini_buildd.models.daemon
import mini_buildd.models.repository
import mini_buildd.models.chroot
import mini_buildd.models.gnupg

LOG = logging.getLogger(__name__)


def gen_uploader_keyrings():
    "Generate all upload keyrings for each repository."
    keyrings = {}
    for r in mini_buildd.models.repository.Repository.mbd_get_active():
        keyrings[r.identity] = r.mbd_get_uploader_keyring()
        # Always add our key too for internal builds
        keyrings[r.identity].add_pub_key(get().model.mbd_get_pub_key())
    return keyrings


def gen_remotes_keyring():
    "Generate the remote keyring to authorize buildrequests and buildresults"
    keyring = mini_buildd.gnupg.TmpGnuPG()
    # Always add our own key
    keyring.add_pub_key(get().model.mbd_get_pub_key())
    for r in mini_buildd.models.gnupg.Remote.mbd_get_active():
        keyring.add_pub_key(r.key)
        LOG.info("Remote key added for '{r}': {k}: {n}".format(r=r, k=r.key_long_id, n=r.key_name).encode("UTF-8"))
    return keyring


def run():
    """
    mini-buildd 'daemon engine' run.
    """

    uploader_keyrings = gen_uploader_keyrings()
    remotes_keyring = gen_remotes_keyring()

    ftpd_thread = mini_buildd.misc.run_as_thread(
        mini_buildd.ftpd.run,
        bind=get().model.ftpd_bind,
        queue=get().incoming_queue)

    builder_thread = mini_buildd.misc.run_as_thread(
        mini_buildd.builder.run,
        queue=get().build_queue,
        builds=get().builds,
        last_builds=get().last_builds,
        remotes_keyring=remotes_keyring,
        gnupg=get().model.mbd_gnupg,
        sbuild_jobs=get().model.sbuild_jobs)

    while True:
        event = get().incoming_queue.get()
        if event == "SHUTDOWN":
            break

        try:
            LOG.info("Status: {0} active packages, {0} changes waiting in incoming.".
                     format(len(get().packages), get().incoming_queue.qsize()))

            changes = None
            changes = mini_buildd.changes.Changes(event)

            if changes.is_buildrequest():
                # Build request: builder

                def queue_buildrequest(event):
                    "Queue in extra thread so we don't block here in case builder is busy."
                    get().build_queue.put(event)
                mini_buildd.misc.run_as_thread(queue_buildrequest, daemon=True, event=event)

            else:
                # User upload or build result: packager
                mini_buildd.packager.run(
                    get().model,
                    changes,
                    get().packages,
                    get().last_packages,
                    remotes_keyring,
                    uploader_keyrings)

        except Exception as e:
            mini_buildd.setup.log_exception(LOG, "Invalid changes file", e)

            # Try to notify
            try:
                subject = "INVALID CHANGES: {c}: {e}".format(c=event, e=e)
                body = email.mime.text.MIMEText(open(event, "rb").read(), _charset="UTF-8")
                get().model.mbd_notify(subject, body)
            except Exception as e:
                mini_buildd.setup.log_exception(LOG, "Invalid changes notify failed", e)

            # Try to clean up
            try:
                if changes:
                    changes.remove()
                else:
                    os.remove(event)
            except Exception as e:
                mini_buildd.setup.log_exception(LOG, "Invalid changes cleanup failed", e)

        finally:
            get().incoming_queue.task_done()

    get().build_queue.put("SHUTDOWN")
    mini_buildd.ftpd.shutdown()
    builder_thread.join()
    ftpd_thread.join()


class Daemon():
    def __init__(self):
        # Vars that are (re)generated when the daemon model is updated
        self.model = None
        self.incoming_queue = None
        self.build_queue = None
        self.packages = None
        self.builds = None
        self.last_packages = None
        self.last_builds = None
        self._update_model()

        # When this is not None, daemon is running
        self.thread = None

        # Set global to ourself
        global _INSTANCE
        _INSTANCE = self

        # Finally, start daemon right now if active
        if self.model.mbd_is_active():
            try:
                self.start(run_check=True, update_model=False)
            except Exception as e:
                mini_buildd.setup.log_exception(LOG, "Could not start daemon", e)
        else:
            LOG.info("Daemon NOT started (activate first)")

    @classmethod
    def _new_model_object(cls):
        model, created = mini_buildd.models.daemon.Daemon.objects.get_or_create(id=1)
        if created:
            LOG.info("New default Daemon model instance created")
        return model

    def _update_model(self):
        self.model = self._new_model_object()

        self.incoming_queue = Queue.Queue()
        self.build_queue = mini_buildd.misc.BlockQueue(maxsize=self.model.build_queue_size)
        self.packages = {}
        self.builds = {}
        self.last_packages = collections.deque(maxlen=self.model.show_last_packages)
        self.last_builds = collections.deque(maxlen=self.model.show_last_builds)

        # Try to unpickle last_* from persistent storage.
        # Objects must match API, and we don't care if it fails.
        try:
            last_packages, last_builds = self.model.mbd_get_pickled_data()
            for p in last_packages:
                if p.api_check():
                    self.last_packages.append(p)
                else:
                    LOG.warn("Removing (new API) from last package info: {p}".format(p=p))
            for b in last_builds:
                if b.api_check():
                    self.last_builds.append(b)
                else:
                    LOG.warn("Removing (new API) from last builds info: {b}".format(b=b))
        except Exception as e:
            LOG.warn("Ignoring error adding persisted last builds/packages: {e}".format(e=e))

    def start(self, run_check, update_model=True):
        if not self.thread:
            if update_model:
                self._update_model()
            if run_check:
                mini_buildd.models.daemon.Daemon.Admin.mbd_action(None, (self.model,), "check")
                if not self.model.mbd_is_active():
                    raise Exception("Daemon auto-deactivated.")

            self.thread = mini_buildd.misc.run_as_thread(run)
            LOG.info("Daemon running")
        else:
            LOG.info("Daemon already running")

    def stop(self):
        if self.thread:
            # Save pickled persistend state; as a workaround, save the whole model but on fresh object/db state.
            # With django 1.5, we could just use save(update_fields=["pickled_data"]) on self.model
            model = self._new_model_object()
            model.mbd_set_pickled_data((self.last_packages, self.last_builds))
            model.save()

            self.incoming_queue.put("SHUTDOWN")
            self.thread.join()
            self.thread = None
            self._update_model()
            LOG.info("Daemon stopped")
        else:
            LOG.info("Daemon already stopped")

    def restart(self, run_check):
        self.stop()
        self.start(run_check)

    def is_running(self):
        return self.thread is not None

    def get_builder_state(self):
        def get_chroots():
            chroots = {}
            for c in mini_buildd.models.chroot.Chroot.mbd_get_active():
                chroots.setdefault(c.architecture.name, [])
                chroots[c.architecture.name].append(c.source.codename)
            return chroots

        return mini_buildd.misc.BuilderState(state=[self.is_running(),
                                                    self.model.mbd_get_ftp_hopo().string,
                                                    self.build_queue.load,
                                                    get_chroots()])

    @property
    def tpl(self):
        return {
            "model": self.model,
            "style": "running" if self.is_running() else "stopped",
            "running_text": "Running" if self.is_running() else "Stopped",
            "packages": self.packages,
            "last_packages": self.last_packages,
            "build_queue": self.build_queue,
            "builds": self.builds,
            "last_builds": self.last_builds}

_INSTANCE = None


def get():
    assert(_INSTANCE)
    return _INSTANCE
