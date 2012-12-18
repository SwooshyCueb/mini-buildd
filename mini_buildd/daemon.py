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
import re
import time
import shutil
import subprocess
import contextlib
import Queue
import collections
import codecs
import email.mime.text
import email.utils
import logging

import debian.deb822

import mini_buildd.misc
import mini_buildd.changes
import mini_buildd.gnupg
import mini_buildd.api
import mini_buildd.ftpd
import mini_buildd.packager
import mini_buildd.builder

import mini_buildd.models.daemon
import mini_buildd.models.repository
import mini_buildd.models.chroot
import mini_buildd.models.gnupg

LOG = logging.getLogger(__name__)


class KeyringPackage(mini_buildd.misc.TmpDir):
    def __init__(self, identity, gpg, debfullname, debemail, tpl_dir="/usr/share/doc/mini-buildd/examples/packages/archive-keyring-template"):
        super(KeyringPackage, self).__init__()

        self.package_name = "{i}-archive-keyring".format(i=identity)
        self.environment = mini_buildd.misc.taint_env(
            {"DEBEMAIL": debemail,
             "DEBFULLNAME": debfullname,
             "GNUPGHOME": gpg.home})
        self.version = time.strftime("%Y%m%d%H%M%S", time.gmtime())

        # Copy template, and replace %ID% and %MAINT% in all files
        p = os.path.join(self.tmpdir, "package")
        shutil.copytree(tpl_dir, p)
        for root, _dirs, files in os.walk(p):
            for f in files:
                old_file = os.path.join(root, f)
                new_file = old_file + ".new"
                codecs.open(new_file, "w", encoding="UTF-8").write(
                    mini_buildd.misc.subst_placeholders(
                        codecs.open(old_file, "r", encoding="UTF-8").read(),
                        {"ID": identity,
                         "MAINT": "{n} <{e}>".format(n=debfullname, e=debemail)}))
                os.rename(new_file, old_file)

        # Export public GnuPG key into the package
        gpg.export(os.path.join(p, self.package_name + ".gpg"))

        # Generate changelog entry
        mini_buildd.misc.call(["debchange",
                               "--create",
                               "--package={p}".format(p=self.package_name),
                               "--newversion={v}".format(v=self.version),
                               "[mini-buildd] Automatic keyring package template for {i}.".format(i=identity)],
                              cwd=p,
                              env=self.environment)

        mini_buildd.misc.call(["dpkg-source",
                               "-b",
                               "package"],
                              cwd=self.tmpdir,
                              env=self.environment)

        # Compute DSC file name
        self.dsc = os.path.join(self.tmpdir,
                                "{p}_{v}.dsc".format(p=self.package_name,
                                                     v=self.version))


@contextlib.contextmanager
def gen_keyring():
    "Generate all upload and remote keyrings."
    keyring = {"uploader": {}, "remotes": mini_buildd.gnupg.TmpGnuPG()}

    # keyring["uploader"]: All uploader keyrings for each repository.
    for r in mini_buildd.models.repository.Repository.mbd_get_active():
        keyring["uploader"][r.identity] = r.mbd_get_uploader_keyring()
        # Always add our key too for internal builds
        keyring["uploader"][r.identity].add_pub_key(get().model.mbd_get_pub_key())

    # keyring["remotes"]: Remotes keyring to authorize buildrequests and buildresults
    # Always add our own key
    keyring["remotes"].add_pub_key(get().model.mbd_get_pub_key())
    for r in mini_buildd.models.gnupg.Remote.mbd_get_active():
        keyring["remotes"].add_pub_key(r.key)
        LOG.info("Remote key added for '{r}': {k}: {n}".format(r=r, k=r.key_long_id, n=r.key_name).encode("UTF-8"))

    try:
        yield keyring
    finally:
        for g in keyring["uploader"].values() + [keyring["remotes"]]:
            g.close()


def run():
    """
    mini-buildd 'daemon engine' run.
    """

    with gen_keyring() as keyring:
        ftpd_thread = mini_buildd.misc.run_as_thread(
            mini_buildd.ftpd.run,
            bind=get().model.ftpd_bind,
            queue=get().incoming_queue)

        builder_thread = mini_buildd.misc.run_as_thread(
            mini_buildd.builder.run,
            queue=get().build_queue,
            builds=get().builds,
            last_builds=get().last_builds,
            remotes_keyring=keyring["remotes"],
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

                if changes.type == changes.TYPE_BREQ:
                    # Build request: builder

                    def queue_buildrequest(event):
                        "Queue in extra thread so we don't block here in case builder is busy."
                        get().build_queue.put(event)
                    mini_buildd.misc.run_as_thread(queue_buildrequest, daemon=True, event=event)

                else:
                    # User upload or build result: packager
                    mini_buildd.packager.run(
                        daemon=get(),
                        changes=changes,
                        packages=get().packages,
                        last_packages=get().last_packages,
                        remotes_keyring=keyring["remotes"],
                        uploader_keyrings=keyring["uploader"])

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
        # Set global to ourself
        global _INSTANCE
        _INSTANCE = self

        # When this is not None, daemon is running
        self.thread = None

        # Vars that are (re)generated when the daemon model is updated
        self.model = None
        self.incoming_queue = None
        self.build_queue = None
        self.packages = None
        self.builds = None
        self.last_packages = None
        self.last_builds = None

        # Finally, start daemon right now if active
        try:
            self.start()
        except Exception as e:
            mini_buildd.setup.log_exception(LOG, "Could not start daemon", e)

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
            mini_buildd.setup.log_exception(LOG, "Error adding persisted last builds/packages (ignoring)", e, logging.WARN)

    def start(self, activate_action=False, request=None):
        if not self.thread:
            self._update_model()

            if not activate_action and (self.model.mbd_is_active() or self.model.auto_reactivate):
                # Check if this can be auto-reactivated
                mini_buildd.models.daemon.Daemon.Admin.mbd_action(request, (self.model,), "check")

            if activate_action or self.model.mbd_is_active():
                self.thread = mini_buildd.misc.run_as_thread(run)
                mini_buildd.models.base.Model.mbd_msg_info(request, "Daemon started.")
            else:
                mini_buildd.models.base.Model.mbd_msg_warn(request, "Daemon deactivated (won't start).")
        else:
            mini_buildd.models.base.Model.mbd_msg_info(request, "Daemon already running.")

    def stop(self, request=None):
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
            mini_buildd.models.base.Model.mbd_msg_info(request, "Daemon stopped.")
        else:
            mini_buildd.models.base.Model.mbd_msg_info(request, "Daemon already stopped.")

    def restart(self, activate_action=False, request=None):
        self.stop(request=request)
        self.start(activate_action=activate_action, request=request)

    def is_running(self):
        return bool(self.thread)

    def get_status(self):
        status = mini_buildd.api.Status([])
        status.run(self)
        return status

    @classmethod
    def logcat(cls, lines):
        logfile = codecs.open(mini_buildd.setup.LOG_FILE, "r", encoding="UTF-8")
        return mini_buildd.misc.tail(logfile, lines)

    @classmethod
    def get_active_chroots(cls):
        return mini_buildd.models.chroot.Chroot.mbd_get_active()

    @classmethod
    def get_active_repositories(cls):
        return mini_buildd.models.repository.Repository.mbd_get_active()

    @classmethod
    def get_active_remotes(cls):
        return mini_buildd.models.gnupg.Remote.mbd_get_active()

    @classmethod
    def parse_distribution(cls, dist):
        """
        Get repository, distribution and suite model objects (plus rollback no) from distribtion string.
        """
        # Check and parse changes distribution string
        dist_parsed = mini_buildd.misc.Distribution(dist)

        # Get repository for identity; django exceptions will suite quite well as-is
        repository = mini_buildd.models.repository.Repository.objects.get(identity=dist_parsed.repository)
        distribution = repository.distributions.all().get(base_source__codename__exact=dist_parsed.codename)
        suite = repository.layout.suiteoption_set.all().get(suite__name=dist_parsed.suite)

        return repository, distribution, suite, dist_parsed.rollback_no

    def port_raw(self, dsc_url, repository, distribution, suite, replace_version_apdx_regex):
        t = mini_buildd.misc.TmpDir()
        try:
            version_apdx = repository.layout.mbd_get_default_version(repository, distribution, suite)
            extra_cl_entries = ["MINI_BUILDD: BACKPORT_MODE"]

            env = mini_buildd.misc.taint_env({"DEBEMAIL": self.model.email_address,
                                              "DEBFULLNAME": self.model.mbd_fullname,
                                              "GNUPGHOME": self.model.mbd_gnupg.home})

            mini_buildd.misc.call(["dget",
                                   "--allow-unauthenticated",
                                   "--download-only",
                                   dsc_url],
                                  cwd=t.tmpdir,
                                  env=env)

            dsc_file = os.path.basename(dsc_url)
            dsc = debian.deb822.Dsc(file(os.path.join(t.tmpdir, dsc_file)))
            dst = "debian_source_tree"

            mini_buildd.misc.call(["dpkg-source",
                                   "-x",
                                   dsc_file,
                                   dst],
                                  cwd=t.tmpdir,
                                  env=env)

            # Remove matching string from version if given; mainly
            # for internal automated backports so they don't get a
            # doubled version apdx like '~testSID+1~test60+1'
            if replace_version_apdx_regex:
                version = re.sub(replace_version_apdx_regex, version_apdx, dsc["Version"])
            else:
                version = dsc["Version"] + version_apdx

            dst_path = os.path.join(t.tmpdir, dst)
            mini_buildd.misc.call(["debchange",
                                   "--newversion={v}".format(v=version),
                                   "--force-distribution",
                                   "--force-bad-version",
                                   "--preserve",
                                   "--dist={d}".format(d=suite.mbd_get_distribution_string(repository, distribution)),
                                   "Automated port via mini-buildd (no changes)."],
                                  cwd=dst_path,
                                  env=env)

            for entry in extra_cl_entries:
                mini_buildd.misc.call(["debchange",
                                       "--append",
                                       entry],
                                      cwd=dst_path,
                                      env=env)

            mini_buildd.misc.call(["dpkg-source", "-b", dst],
                                  cwd=t.tmpdir,
                                  env=env)

            changes = os.path.join(t.tmpdir,
                                   mini_buildd.changes.Changes.gen_changes_file_name(dsc["Source"],
                                                                                     version,
                                                                                     "source"))

            with open(changes, "w") as c:
                subprocess.check_call(["dpkg-genchanges",
                                       "-S",
                                       "-sa"],
                                      cwd=dst_path,
                                      env=env,
                                      stdout=c)

            self.model.mbd_gnupg.sign(changes)
            self.incoming_queue.put(changes)
        except:
            t.close()
            raise

    def port(self, dsc_url, dist, replace_version_apdx_regex):
        repository, distribution, suite, rollback = self.parse_distribution(dist)

        if not suite.uploadable:
            raise Exception("Port failed: Non-upload distribution requested: '{d}'".format(d=dist))

        if rollback:
            raise Exception("Port failed: Rollback distribution requested: '{d}'".format(d=dist))

        self.port_raw(dsc_url, repository, distribution, suite, replace_version_apdx_regex)

    def get_keyring_package(self):
        return KeyringPackage(self.model.identity,
                              self.model.mbd_gnupg,
                              self.model.mbd_fullname,
                              self.model.email_address)

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
