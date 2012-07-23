# -*- coding: utf-8 -*-
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
import mini_buildd.builder

from mini_buildd.models.repository import EmailAddress, Repository
from mini_buildd.models.chroot import Chroot
from mini_buildd.models.gnupg import Remote
from mini_buildd.models.base import StatusModel

LOG = logging.getLogger(__name__)


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
        self._mbd_fullname = "mini-buildd archive {i}".format(i=self.identity)
        self._mbd_gnupg = mini_buildd.gnupg.GnuPG(self.gnupg_template, self._mbd_fullname, self.email_address)

        self.mbd_incoming_queue = Queue.Queue(maxsize=self.incoming_queue_size)
        self.mbd_build_queue = Queue.Queue(maxsize=self.build_queue_size)
        self.mbd_packages = {}
        self.mbd_builder_status = mini_buildd.builder.Status(self.build_queue_size)
        self.mbd_stray_buildresults = []

    @property
    def mbd_fullname(self):
        return self._mbd_fullname

    @property
    def mbd_gnupg(self):
        return self._mbd_gnupg

    def __unicode__(self):
        return u"{i}: Serving {r} repositories, {c} chroots, {R} remotes ({s})".format(
            i=self.identity,
            r=len(Repository.objects.filter(status=Repository.STATUS_ACTIVE)),
            c=len(Chroot.objects.filter(status=Chroot.STATUS_ACTIVE)),
            R=len(Remote.objects.filter(status=Remote.STATUS_ACTIVE)),
            s=self.get_status_display())

    def clean(self, *args, **kwargs):
        super(Daemon, self).clean(*args, **kwargs)
        if Daemon.objects.count() > 0 and self.id != Daemon.objects.get().id:
            raise django.core.exceptions.ValidationError("You can only create one Daemon instance!")

    def mbd_prepare(self, request):
        self._mbd_gnupg.prepare()
        self.mbd_msg_info(request, "Daemon GnuPG key generated")

    def mbd_unprepare(self, request):
        self._mbd_gnupg.unprepare()
        self.mbd_msg_info(request, "Daemon GnuPG key removed")

    def mbd_activate(self, request):
        import mini_buildd.daemon
        mini_buildd.daemon.get().restart()
        self.mbd_msg_info(request, "Daemon restarted")

    def mbd_deactivate(self, request):
        import mini_buildd.daemon
        mini_buildd.daemon.get().stop()
        self.mbd_msg_info(request, "Daemon stopped")

    def mbd_get_ftp_hopo(self):
        return mini_buildd.misc.HoPo(u"{h}:{p}".format(h=self.hostname, p=mini_buildd.misc.HoPo(self.ftpd_bind).port))

    def mbd_get_ftp_url(self):
        return u"ftp://{h}".format(h=self.mbd_get_ftp_hopo().string)

    def mbd_get_http_hopo(self):
        return mini_buildd.misc.HoPo(u"{h}:{p}".format(h=self.hostname, p=mini_buildd.misc.HoPo(mini_buildd.setup.HTTPD_BIND).port))

    def mbd_get_http_url(self):
        return u"http://{h}".format(h=self.mbd_get_http_hopo().string)

    def mbd_get_pub_key(self):
        return self._mbd_gnupg.get_pub_key()

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
                LOG.warn("EMail address does not match allowed regex '{r}' (ignoring): {a}".format(r=self.allow_emails_to, a=address))

        m_from = "{u}@{h}".format(u="mini-buildd", h=self.hostname)

        for m in self.notify.all():
            add_to(m.address)
        if repository:
            for m in repository.notify.all():
                add_to(m.address)
            if changes:
                if repository.notify_maintainer:
                    add_to(email.utils.parseaddr(changes.get_or_empty("Maintainer"))[1])
                if repository.notify_changed_by:
                    add_to(email.utils.parseaddr(changes.get_or_empty("Changed-By"))[1])

        if m_to:
            try:
                body['Subject'] = subject
                body['From'] = m_from
                body['To'] = ", ".join(m_to)

                hopo = mini_buildd.misc.HoPo(self.smtp_server)
                s = smtplib.SMTP(hopo.host, hopo.port)
                s.sendmail(m_from, m_to, body.as_string())
                s.quit()
                LOG.info("Sent: Mail '{s}' to '{r}'".format(s=subject, r=str(m_to)))
            except Exception as e:
                LOG.error("Mail sending failed: '{s}' to '{r}': {e}".format(s=subject, r=str(m_to), e=str(e)))
        else:
            LOG.warn("No email addresses found, skipping: {s}".format(s=subject))

django.contrib.admin.site.register(Daemon, Daemon.Admin)
