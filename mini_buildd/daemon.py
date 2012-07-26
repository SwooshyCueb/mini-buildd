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

import os
import shutil
import re
import email.mime.text
import email.utils
import logging

import mini_buildd.misc
import mini_buildd.changes
import mini_buildd.gnupg
import mini_buildd.ftpd
import mini_buildd.builder

import mini_buildd.models.daemon
import mini_buildd.models.repository
import mini_buildd.models.chroot
import mini_buildd.models.gnupg

LOG = logging.getLogger(__name__)


class Package(object):
    DONE = 0
    INCOMPLETE = 1

    def __init__(self, changes, repository, dist, suite):
        self.changes = changes
        self.repository, self.dist, self.suite = repository, dist, suite
        self.pid = changes.get_pkg_id()
        self.requests = self.changes.gen_buildrequests(get().model, self.repository, self.dist)
        self.success = {}
        self.failed = {}
        for _key, breq in self.requests.items():
            breq.upload_buildrequest(get().model.mbd_get_http_hopo())

    def notify(self):
        results = u""
        for arch, c in self.failed.items() + self.success.items():
            for fd in c.get_files():
                f = fd["name"]
                if re.compile("^.*\.buildlog$").match(f):
                    results += u"{s}({a}): {b}\n".format(s=c["Sbuild-Status"], a=arch, b=get().model.mbd_get_http_url() + "/" +
                                                         os.path.join(u"log", c["Distribution"], c["Source"], c["Version"], arch, f))

        results += u"\n"
        body = email.mime.text.MIMEText(results + self.changes.dump(), _charset="UTF-8")

        get().model.mbd_notify(
            "{s}: {p} ({f}/{r} failed)".format(
                s="Failed" if self.failed else "Build",
                p=self.pid, f=len(self.failed), r=len(self.requests)),
            body,
            self.repository,
            self.changes)

    def update(self, result):
        arch = result["Architecture"]
        status = result["Sbuild-Status"]
        retval = int(result["Sbuildretval"])
        LOG.info("{p}: Got build result for '{a}': {r} ({s})".format(p=self.pid, a=arch, r=retval, s=status))

        if retval == 0:
            self.success[arch] = result
        else:
            self.failed[arch] = result

        missing = len(self.requests) - len(self.success) - len(self.failed)
        if missing > 0:
            LOG.debug("{p}: {n} arches still missing.".format(p=self.pid, n=missing))
            return self.INCOMPLETE

        # Finish up
        LOG.info("{p}: All build results received".format(p=self.pid))
        try:
            if self.failed:
                raise Exception("{p}: {n} mandatory architecture(s) failed".format(p=self.pid, n=len(self.failed)))

            for arch, c in self.success.items():
                c.untar(path=self.repository.mbd_get_incoming_path())
                self.repository.mbd_reprepro().processincoming()
        except Exception as e:
            LOG.error(str(e))
            # todo Error!
        finally:
            # Archive build results and request
            for arch, c in self.success.items() + self.failed.items() + self.requests.items():
                c.archive()
            # Archive incoming changes
            self.changes.archive()
            # Purge complete package dir
            shutil.rmtree(self.changes.get_spool_dir())

            self.notify()
        return self.DONE


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
        LOG.info(u"Remote key added for '{r}': {k}: {n}".format(r=r, k=r.key_long_id, n=r.key_name).encode("UTF-8"))
    return keyring


def handle_buildresult(bres):
    pid = bres.get_pkg_id()
    if pid in get().model.mbd_packages:
        if get().model.mbd_packages[pid].update(bres) == Package.DONE:
            del get().model.mbd_packages[pid]
        return True
    return False


def run():
    """
    mini-buildd 'daemon engine' run.
    """

    uploader_keyrings = gen_uploader_keyrings()
    remotes_keyring = gen_remotes_keyring()

    ftpd_thread = mini_buildd.misc.run_as_thread(
        mini_buildd.ftpd.run,
        bind=get().model.ftpd_bind,
        queue=get().model.mbd_incoming_queue)

    builder_thread = mini_buildd.misc.run_as_thread(
        mini_buildd.builder.run,
        gnupg=get().model.mbd_gnupg,
        queue=get().model.mbd_build_queue,
        status=get().model.mbd_builder_status,
        build_queue_size=get().model.build_queue_size,
        sbuild_jobs=get().model.sbuild_jobs)

    while True:
        event = get().model.mbd_incoming_queue.get()
        if event == "SHUTDOWN":
            break

        try:
            LOG.info("Status: {0} active packages, {0} changes waiting in incoming.".
                     format(len(get().model.mbd_packages), get().model.mbd_incoming_queue.qsize()))

            changes, changes_pid = None, None
            changes = mini_buildd.changes.Changes(event)
            changes_pid = changes.get_pkg_id()

            if changes.is_buildrequest():
                remotes_keyring.verify(changes.file_path)
                get().model.mbd_build_queue.put(event)
            elif changes.is_buildresult():
                remotes_keyring.verify(changes.file_path)
                if not handle_buildresult(changes):
                    get().model.mbd_stray_buildresults.append(changes)
            else:
                repository, dist, suite = changes.get_repository()
                if repository.allow_unauthenticated_uploads:
                    LOG.warn("Unauthenticated uploads allowed. Using '{c}' unchecked".format(c=changes.file_name))
                else:
                    uploader_keyrings[repository.identity].verify(changes.file_path)

                get().model.mbd_packages[changes_pid] = Package(changes, repository, dist, suite)

                for bres in get().model.mbd_stray_buildresults:
                    handle_buildresult(bres)

        except Exception as e:
            if changes and changes_pid:
                subject = u"DISCARD: {p}: {e}".format(p=changes_pid, e=str(e))
                body = email.mime.text.MIMEText(changes.dump(), _charset="UTF-8")
                changes.remove()
            else:
                subject = u"INVALID CHANGES: {c}: {e}".format(c=event, e=str(e))
                body = email.mime.text.MIMEText(open(event, "rb").read(), _charset="UTF-8")
                os.remove(event)
            LOG.warn(subject)
            get().model.mbd_notify(subject, body)

            if mini_buildd.setup.DEBUG is not None and "main" in mini_buildd.setup.DEBUG:
                LOG.exception("DEBUG: Daemon loop exception")

        finally:
            get().model.mbd_incoming_queue.task_done()

    get().model.mbd_build_queue.put("SHUTDOWN")
    mini_buildd.ftpd.shutdown()
    builder_thread.join()
    ftpd_thread.join()


class Manager():
    def __init__(self):
        self.model = None
        self.update_model()
        self.thread = None
        global _INSTANCE
        _INSTANCE = self
        if self.model.mbd_is_active():
            self.start(run_check=True)
        else:
            LOG.info("Daemon NOT started (activate first)")

    def update_model(self):
        self.model, created = mini_buildd.models.daemon.Daemon.objects.get_or_create(id=1)
        if created:
            LOG.info("New default Daemon model instance created")
        LOG.info("Daemon model instance updated...")

    def start(self, run_check):
        if not self.thread:
            self.update_model()
            if run_check:
                self.model.mbd_check(request=None)
            self.thread = mini_buildd.misc.run_as_thread(run)
            LOG.info("Daemon running")
        else:
            LOG.info("Daemon already running")

    def stop(self):
        if self.thread:
            self.model.mbd_incoming_queue.put("SHUTDOWN")
            self.thread.join()
            self.thread = None
            self.update_model()
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
                                                    self.model.mbd_builder_status.load(),
                                                    get_chroots()])

    def status_as_html(self):
        """.. todo:: This should be mutex-locked. """
        def packages():
            packages = "<ul>"
            for p in self.model.mbd_packages:
                packages += "<li>{p}</li>".format(p=p)
            packages += "</ul>"
            return packages

        def remotes():
            remotes = "<ul>"
            for r in mini_buildd.models.gnupg.Remote.mbd_get_active():
                remotes += "<li>{r}</li>".format(r=r)
            remotes += "</ul>"
            return remotes

        return u'''
<h1 class="box-caption">Status: <span class="status {style}">{s}</span></h1>

<h2>Daemon: {id}</h2>

<ul>
  <li>{c} changes files pending in incoming.</li>
  <li>{b} build requests pending in queue.</li>
</ul>

<hr />

<h3>Packager: {p} active packages</h3>
{packages}

<hr />

{builder_status}

<hr />

<h4>Remotes: {r} active</h3>

{remote_status}

'''.format(style="running" if self.is_running() else "stopped",
           s="Running" if self.is_running() else "Stopped",
           id=self.model,
           c=self.model.mbd_incoming_queue.qsize(),
           b=self.model.mbd_build_queue.qsize(),
           p=len(self.model.mbd_packages),
           packages=packages(),
           builder_status=self.model.mbd_builder_status.get_html(),
           r=len(mini_buildd.models.gnupg.Remote.mbd_get_active()),
           remote_status=remotes())

_INSTANCE = None


def get():
    assert(_INSTANCE)
    return _INSTANCE
