# -*- coding: utf-8 -*-
import os, shutil, re, Queue, contextlib, socket, smtplib, logging

from email.mime.text import MIMEText
import email.utils

import django.db, django.core.exceptions, django.contrib.auth.models

from mini_buildd import misc, changes, gnupg, ftpd, builder

from mini_buildd.models import StatusModel, Repository, Chroot, EmailAddress, msg_info, msg_warn, msg_error

log = logging.getLogger(__name__)

class Daemon(StatusModel):
    # Basics
    hostname = django.db.models.CharField(
        max_length=200,
        default=socket.getfqdn(),
        help_text="Fully qualified hostname.")

    ftpd_bind = django.db.models.CharField(
        max_length=200,
        default="0.0.0.0:8067",
        help_text="FTP Server IP/Hostname and port to bind to.")

    # GnuPG options
    gnupg_template = django.db.models.TextField(default="""
Key-Type: DSA
Key-Length: 2048
Expire-Date: 0
""")

    gnupg_keyserver = django.db.models.CharField(
        max_length=200,
        default="subkeys.pgp.net",
        help_text="GnuPG keyserver to use.")

    # Load options
    incoming_queue_size = django.db.models.SmallIntegerField(
        default=2*misc.get_cpus(),
        help_text="Maximum number of parallel packages to process.")

    build_queue_size = django.db.models.SmallIntegerField(
        default=misc.get_cpus(),
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
            ("Basics", {
                    "fields": ("hostname", "ftpd_bind", "gnupg_template", "gnupg_keyserver")
                    }),
            ("Load Options", {
                    "fields": ("incoming_queue_size", "build_queue_size", "sbuild_jobs")
                    }),
            ("E-Mail Options", {
                    "fields": ("smtp_server", "notify", "allow_emails_to")
                    }))

    def __init__(self, *args, **kwargs):
        ".. todo:: GPG: to be replaced in template; Only as long as we don't know better"
        super(Daemon, self).__init__(*args, **kwargs)
        self._gnupg = gnupg.GnuPG(self.gnupg_template)
        self._incoming_queue = Queue.Queue(maxsize=self.incoming_queue_size)
        self._build_queue = Queue.Queue(maxsize=self.build_queue_size)
        self._packages = {}

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
        msg_info(r, "Preparing GnuPG...")
        self._gnupg.prepare()

    def mbd_activate(self, r):
        msg_info(r, "(Re-)starting daemon...")
        get().start()

    def mbd_deactivate(self, r):
        msg_info(r, "Stopping daemon...")
        get().stop()

    def mbd_get_ftp_url(self):
        ba = misc.BindArgs(self.ftpd_bind)
        return u"ftp://{h}:{p}".format(h=self.hostname, p=ba.port)

    def mbd_get_http_url(self):
        ".. todo:: Port should be the one given with args, not hardcoded."
        #ba = misc.BindArgs(self.ftpd_bind)
        return u"http://{h}:{p}".format(h=self.hostname, p=8066)

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

                ba = misc.BindArgs(self.smtp_server)
                s = smtplib.SMTP(ba.host, ba.port)
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

    def __init__(self, changes):
        self.changes = changes
        self.pid = changes.get_pkg_id()
        try:
            self.repository, self.dist, self.suite = changes.get_repository()
            self.requests = self.changes.gen_buildrequests(self.repository, self.dist)
            self.success = {}
            self.failed = {}
            self.request_missing_builds()
        except Exception as e:
            log.warn("Initial QA failed in changes: {e}: ".format(e=str(e)))
            body = MIMEText(self.changes.dump(), _charset="UTF-8")
            get().model.mbd_notify("DISCARD: {p}: {e}".format(p=self.pid, e=str(e)), body)
            raise

    def request_missing_builds(self):
        log.info(self.requests)
        for key, r in self.requests.items():
            log.info(str(key))
            log.info(repr(r))
            if key not in self.success:
                r.upload()

    def notify(self):
        results = u""
        for arch, c in self.failed.items() + self.success.items():
            for fd in c.get_files():
                results += u"{s}({a}): {b}\n".format(s=c["Sbuild-Status"], a=arch, b=get().model.mbd_get_http_url() + "/" +
                                                     os.path.join(u"log", c["Distribution"], c["Source"], c["Version"], arch, fd["name"]))

        results += u"\n"
        body = MIMEText(results + self.changes.dump(), _charset="UTF-8")

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
                raise Exception("{p}: {n} Mandatory architectures failed".format(p=self.pid, n=len(self.failed)))

            for arch, c in self.success.items():
                c.untar(path=self.repository.mbd_get_incoming_path())
                self.repository._reprepro.processincoming()
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

def run():
    """.. todo:: Own GnuPG model """
    # Get/Create daemon model instance (singleton-like)
    dm = get().model

    # Start ftpd and builder
    ftpd_thread = misc.run_as_thread(ftpd.run, bind=dm.ftpd_bind, queue=dm._incoming_queue)
    builder_thread = misc.run_as_thread(builder.run, build_queue=dm._build_queue, sbuild_jobs=dm.sbuild_jobs)

    stray_buildresults = []

    while True:
        log.info("Status: {0} active packages, {0} changes waiting in incoming.".
                 format(len(dm._packages), dm._incoming_queue.qsize()))

        event = dm._incoming_queue.get()
        if event == "SHUTDOWN":
            dm._build_queue.put("SHUTDOWN")
            ftpd.shutdown()
            break

        try:
            def update_packages(build_result):
                pid = build_result.get_pkg_id()
                if pid in dm._packages:
                    if dm._packages[pid].update(build_result) == Package.DONE:
                        del dm._packages[pid]
                    return True
                return False

            c = changes.Changes(event)
            if c.is_buildrequest():
                dm._build_queue.put(event)
            elif c.is_buildresult():
                if not update_packages(c):
                    stray_buildresults.append(c)
            else:
                pid = c.get_pkg_id()
                dm._packages[pid] = Package(c)
                for br in stray_buildresults:
                    update_packages(br)

        except Exception as e:
            log.exception("Exception in daemon loop: {e}".format(e=str(e)))
        finally:
            dm._incoming_queue.task_done()

    builder_thread.join()
    ftpd_thread.join()

class _Daemon():
    def update_model(self):
        self.model, created = Daemon.objects.get_or_create(id=1)
        if created:
            log.info("New default Daemon model instance created")
        log.info("Model instance updated...")

    def __init__(self):
        self.update_model()
        self.daemon_thread = None
        global _INSTANCE
        _INSTANCE = self

    def start(self):
        if not self.daemon_thread:
            self.daemon_thread = misc.run_as_thread(run)

    def stop(self):
        if self.daemon_thread:
            self.model._incoming_queue.put("SHUTDOWN")
            self.daemon_thread.join()
        self.daemon_thread = None

    def reload(self):
        self.stop()
        self.update_model()
        self.start()

    def is_running(self):
        return self.daemon_thread != None

def get():
    global _INSTANCE
    assert(_INSTANCE)
    return _INSTANCE
