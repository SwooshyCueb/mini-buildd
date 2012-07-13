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
import Queue
import socket
import smtplib
import email.mime.text
import email.utils
import logging

import django.db
import django.core.exceptions
import django.contrib.auth.models

import mini_buildd.misc
import mini_buildd.changes
import mini_buildd.gnupg
import mini_buildd.ftpd
import mini_buildd.builder

from mini_buildd.models import StatusModel, Repository, Chroot, EmailAddress, msg_info

log = logging.getLogger(__name__)


class Daemon(StatusModel):
    # Basics
    identity = django.db.models.CharField(max_length=50, default=socket.gethostname())

    hostname = django.db.models.CharField(
        max_length=200,
        default=socket.getfqdn(),
        help_text="Fully qualified hostname.")

    email_address = django.db.models.EmailField(max_length=255, default="mini-buildd@{h}".format(h=socket.getfqdn()))

    # GnuPG options
    gnupg_template = django.db.models.TextField(default="""
Key-Type: DSA
Key-Length: 2048
Expire-Date: 0
""")

    gnupg_keyserver = django.db.models.CharField(
        max_length=200,
        default="subkeys.pgp.net",
        help_text="GnuPG keyserver to use (as fill-in helper).")

    ftpd_bind = django.db.models.CharField(
        max_length=200,
        default="0.0.0.0:8067",
        help_text="FTP Server IP/Hostname and port to bind to.")

    # Load options
    incoming_queue_size = django.db.models.SmallIntegerField(
        default=2 * mini_buildd.misc.get_cpus(),
        help_text="Maximum number of parallel packages to process.")

    build_queue_size = django.db.models.SmallIntegerField(
        default=mini_buildd.misc.get_cpus(),
        help_text="Maximum number of parallel builds.")

    sbuild_jobs = django.db.models.SmallIntegerField(
        default=1,
        help_text="Degree of parallelism per build (via sbuild's '--jobs' option).")

    # EMail options
    smtp_server = django.db.models.CharField(
        max_length=254,
        default="{h}:25".format(h=socket.getfqdn()),
        help_text="SMTP server (and optionally port) for mail sending.")

    notify = django.db.models.ManyToManyField(EmailAddress, blank=True)
    allow_emails_to = django.db.models.CharField(
        max_length=254,
        default=".*@{h}".format(h=socket.getfqdn()),
        help_text="""\
Regex to allow sending E-Mails to. Use '.*' to allow all -- it's
however recommended to put this to s.th. like '.*@myemail.domain', to
prevent original package maintainers to be spammed.

[Spamming could occur if you enable the 'Changed-By' or
'Maintainer' notify options in repositories.]
""")

    class Meta(StatusModel.Meta):
        verbose_name_plural = "Daemon"

    class Admin(StatusModel.Admin):
        fieldsets = (
            ("Archive identity", {"fields": ("identity", "hostname", "email_address", "gnupg_template")}),
            ("FTP (incoming) Options", {"fields": ("ftpd_bind",)}),
            ("Load Options", {"fields": ("incoming_queue_size", "build_queue_size", "sbuild_jobs")}),
            ("E-Mail Options", {"fields": ("smtp_server", "notify", "allow_emails_to")}),
            ("Other Options", {"fields": ("gnupg_keyserver",)}))

    def __init__(self, *args, **kwargs):
        super(Daemon, self).__init__(*args, **kwargs)
        self._fullname = "mini-buildd archive {i}".format(i=self.identity)
        self._gnupg = mini_buildd.gnupg.GnuPG(self.gnupg_template, self._fullname, self.email_address)
        self._incoming_queue = Queue.Queue(maxsize=self.incoming_queue_size)
        self._build_queue = Queue.Queue(maxsize=self.build_queue_size)
        self._packages = {}
        self._builder_status = mini_buildd.builder.Status(self.build_queue_size)
        self._stray_buildresults = []

    def __unicode__(self):
        reps = []
        for r in Repository.objects.all():
            reps.append(r.__unicode__())
        chroots = []
        for c in Chroot.objects.all():
            chroots.append(c.__unicode__())
        return u"Repositories: {r} | Chroots: {c}".format(r=",".join(reps), c=",".join(chroots))

    def clean(self):
        super(Daemon, self).clean()
        if Daemon.objects.count() > 0 and self.id != Daemon.objects.get().id:
            raise django.core.exceptions.ValidationError("You can only create one Daemon instance!")

    def mbd_prepare(self, r):
        self._gnupg.prepare(r)

    def mbd_unprepare(self, r):
        self._gnupg.unprepare(r)

    def mbd_activate(self, r):
        get().restart(r)

    def mbd_deactivate(self, r):
        get().stop(r)

    def mbd_get_ftp_hopo(self):
        return mini_buildd.misc.HoPo(u"{h}:{p}".format(h=self.hostname, p=mini_buildd.misc.HoPo(self.ftpd_bind).port))

    def mbd_get_ftp_url(self):
        return u"ftp://{h}".format(h=self.mbd_get_ftp_hopo().string)

    def mbd_get_http_hopo(self):
        return mini_buildd.misc.HoPo(u"{h}:{p}".format(h=self.hostname, p=mini_buildd.misc.HoPo(mini_buildd.setup.HTTPD_BIND).port))

    def mbd_get_http_url(self):
        return u"http://{h}".format(h=self.mbd_get_http_hopo().string)

    def mbd_get_pub_key(self):
        return self._gnupg.get_pub_key()

    def mbd_get_dput_conf(self):
        return """\
[mini-buildd-{h}]
method   = ftp
fqdn     = {hostname}:{p}
login    = anonymous
incoming = /incoming
""".format(h=self.hostname.split(".")[0], hostname=self.hostname, p=8067)

    def mbd_notify(self, subject, body, repository=None, changes=None):
        m_to = []
        m_to_allow = re.compile(self.allow_emails_to)

        def add_to(address):
            if address and m_to_allow.search(address):
                m_to.append(address)
            else:
                log.warn("EMail address does not match allowed regex '{r}' (ignoring): {a}".format(r=self.allow_emails_to, a=address))

        m_from = "{u}@{h}".format(u="mini-buildd", h=self.hostname)

        for m in self.notify.all():
            add_to(m.address)
        if repository:
            for m in repository.notify.all():
                add_to(m.address)
            if changes:
                if repository.notify_maintainer:
                    add_to(email.utils.parseaddr(changes.get("Maintainer"))[1])
                if repository.notify_changed_by:
                    add_to(email.utils.parseaddr(changes.get("Changed-By"))[1])

        if m_to:
            try:
                body['Subject'] = subject
                body['From'] = m_from
                body['To'] = ", ".join(m_to)

                hopo = mini_buildd.misc.HoPo(self.smtp_server)
                s = smtplib.SMTP(hopo.host, hopo.port)
                s.sendmail(m_from, m_to, body.as_string())
                s.quit()
                log.info("Sent: Mail '{s}' to '{r}'".format(s=subject, r=str(m_to)))
            except Exception as e:
                log.error("Mail sending failed: '{s}' to '{r}': {e}".format(s=subject, r=str(m_to), e=str(e)))
        else:
            log.warn("No email addresses found, skipping: {s}".format(s=subject))

django.contrib.admin.site.register(Daemon, Daemon.Admin)


class Package(object):
    DONE = 0
    INCOMPLETE = 1

    def __init__(self, changes, repository, dist, suite):
        self.changes = changes
        self.repository, self.dist, self.suite = repository, dist, suite
        self.pid = changes.get_pkg_id()
        self.requests = self.changes.gen_buildrequests(self.repository, self.dist)
        self.success = {}
        self.failed = {}
        for key, breq in self.requests.items():
            breq.upload_buildrequest()

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
        log.info("{p}: Got build result for '{a}': {r} ({s})".format(p=self.pid, a=arch, r=retval, s=status))

        if retval == 0:
            self.success[arch] = result
        else:
            self.failed[arch] = result

        missing = len(self.requests) - len(self.success) - len(self.failed)
        if missing > 0:
            log.debug("{p}: {n} arches still missing.".format(p=self.pid, n=missing))
            return self.INCOMPLETE

        # Finish up
        log.info("{p}: All build results received".format(p=self.pid))
        try:
            if self.failed:
                raise Exception("{p}: {n} mandatory architecture(s) failed".format(p=self.pid, n=len(self.failed)))

            for arch, c in self.success.items():
                c.untar(path=self.repository.mbd_get_incoming_path())
                self.repository.mbd_reprepro().processincoming()
        except Exception as e:
            log.error(str(e))
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
    for r in Repository.objects.all():
        keyrings[r.identity] = r.mbd_get_uploader_keyring()
        # Always add our key too for internal builds
        keyrings[r.identity].add_pub_key(get().model.mbd_get_pub_key())
    return keyrings


def gen_remotes_keyring():
    "Generate the remote keyring to authorize buildrequests and buildresults"
    from mini_buildd.models import Remote
    keyring = mini_buildd.gnupg.TmpGnuPG()
    # Always add our own key
    keyring.add_pub_key(get().model.mbd_get_pub_key())
    for r in Remote.objects.all():
        keyring.add_pub_key(r.key)
        log.info(u"Remote key added for '{r}': {k}: {n}".format(r=r, k=r.key_long_id, n=r.key_name).encode("UTF-8"))
    return keyring


def run():
    """ mini-buildd 'daemon engine' run.
    """

    def handle_buildresult(bres):
        pid = bres.get_pkg_id()
        if pid in get().model._packages:
            if get().model._packages[pid].update(bres) == Package.DONE:
                del get().model._packages[pid]
            return True
        return False

    uploader_keyrings = gen_uploader_keyrings()
    remotes_keyring = gen_remotes_keyring()

    ftpd_thread = mini_buildd.misc.run_as_thread(
        mini_buildd.ftpd.run,
        bind=get().model.ftpd_bind,
        queue=get().model._incoming_queue)

    builder_thread = mini_buildd.misc.run_as_thread(
        mini_buildd.builder.run,
        queue=get().model._build_queue,
        status=get().model._builder_status,
        build_queue_size=get().model.build_queue_size,
        sbuild_jobs=get().model.sbuild_jobs)

    while True:
        event = get().model._incoming_queue.get()
        if event == "SHUTDOWN":
            break

        try:
            log.info("Status: {0} active packages, {0} changes waiting in incoming.".
                     format(len(get().model._packages), get().model._incoming_queue.qsize()))

            changes, changes_pid = None, None
            changes = mini_buildd.changes.Changes(event)
            changes_pid = changes.get_pkg_id()

            if changes.is_buildrequest():
                remotes_keyring.verify(changes._file_path)
                get().model._build_queue.put(event)
            elif changes.is_buildresult():
                remotes_keyring.verify(changes._file_path)
                if not handle_buildresult(changes):
                    get().model._stray_buildresults.append(changes)
            else:
                repository, dist, suite = changes.get_repository()
                if repository.allow_unauthenticated_uploads:
                    log.warn("Unauthenticated uploads allowed. Using '{c}' unchecked".format(c=changes._file_name))
                else:
                    uploader_keyrings[repository.identity].verify(changes._file_path)

                get().model._packages[changes_pid] = Package(changes, repository, dist, suite)

                for bres in get().model._stray_buildresults:
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
            log.warn(subject)
            get().model.mbd_notify(subject, body)

            if mini_buildd.setup.DEBUG is not None and "main" in mini_buildd.setup.DEBUG:
                log.exception("DEBUG: Daemon loop exception")

        finally:
            get().model._incoming_queue.task_done()

    get().model._build_queue.put("SHUTDOWN")
    mini_buildd.ftpd.shutdown()
    builder_thread.join()
    ftpd_thread.join()


class Manager():
    def __init__(self):
        self.update_model()
        self.thread = None
        global _INSTANCE
        _INSTANCE = self
        if self.model.status == StatusModel.STATUS_ACTIVE:
            self.start()
        else:
            log.info("Daemon NOT started (activate first)")

    def update_model(self):
        self.model, created = Daemon.objects.get_or_create(id=1)
        if created:
            log.info("New default Daemon model instance created")
        log.info("Daemon model instance updated...")

    def start(self, r=None):
        if not self.thread:
            self.update_model()
            self.thread = mini_buildd.misc.run_as_thread(run)
            msg_info(r, "Daemon started")
        else:
            msg_info(r, "Daemon already started")

    def stop(self, r=None):
        if self.thread:
            self.model._incoming_queue.put("SHUTDOWN")
            self.thread.join()
            self.thread = None
            self.update_model()
            msg_info(r, "Daemon stopped")
        else:
            msg_info(r, "Daemon already stopped")

    def restart(self, r=None):
        self.stop(r)
        self.start(r)

    def is_running(self):
        return self.thread is not None

    def get_builder_state(self):
        def get_chroots():
            chroots = {}
            for c in Chroot.objects.filter(status=mini_buildd.models.StatusModel.STATUS_ACTIVE):
                chroots.setdefault(c.architecture.name, [])
                chroots[c.architecture.name].append(c.source.codename)
            return chroots

        return mini_buildd.misc.BuilderState(state=[self.is_running(),
                                                    self.model.mbd_get_ftp_hopo().string,
                                                    self.model._builder_status.load(),
                                                    get_chroots()])

    def status_as_html(self):
        """.. todo:: This should be mutex-locked. """
        def packages():
            packages = "<ul>"
            for p in self.model._packages:
                packages += "<li>{p}</li>".format(p=p)
            packages += "</ul>"
            return packages

        return u'''
<h1 class="box-caption">Status: <span class="status {style}">{s}</span></h1>

<h2>Daemon: {id}</h2>

<ul>
  <li>{c} changes files pending in incoming.</li>
  <li>{b} build requests pending in queue.</li>
</ul>

<hr/>

<h3>Packager: {p} active packages</h3>
{packages}

<hr/>

{builder_status}
'''.format(style="running" if self.is_running() else "stopped",
           s="Running" if self.is_running() else "Stopped",
           id=self.model,
           c=self.model._incoming_queue.qsize(),
           b=self.model._build_queue.qsize(),
           p=len(self.model._packages),
           packages=packages(),
           builder_status=self.model._builder_status.get_html())


_INSTANCE = None


def get():
    global _INSTANCE
    assert(_INSTANCE)
    return _INSTANCE
