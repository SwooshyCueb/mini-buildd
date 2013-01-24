# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import re
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

import mini_buildd.models.base
import mini_buildd.models.repository
import mini_buildd.models.chroot
import mini_buildd.models.gnupg


LOG = logging.getLogger(__name__)


class Daemon(mini_buildd.models.base.StatusModel):
    # Basics
    identity = django.db.models.CharField(max_length=50, default=socket.gethostname(),
                                          help_text="""\
Daemon's identity; this will be used to identify this
mini-buildd instance in various places.

It will occur in the "Name-Real" part of the GnuPG key,
determines the name of the automated keyring packages, and will
also occur in the "Origin" tag of repository indices.

In most cases, just name of the host we are running on is a good
choice.
""")

    hostname = django.db.models.CharField(
        max_length=200,
        default=socket.getfqdn(),
        help_text="Fully qualified hostname we can be accesed through by others over the network (i.e, from users, uploaders or remotes).")

    email_address = django.db.models.EmailField(max_length=255, default="mini-buildd@{h}".format(h=socket.getfqdn()),
                                                help_text="""\
Daemon's email address; this will be used to identify this
mini-buildd instance in various places.

It will occur in the "Name-Email" part of the GnuPG key, and used as
maintainer email on various occations when packages are build
automatically.
""")

    # GnuPG options
    gnupg_template = django.db.models.TextField(default="""
Key-Type: RSA
Key-Length: 4096
Expire-Date: 0
""", help_text="""
Template as accepted by 'gpg --batch --gen-key' (see 'man gpg').

You should not give 'Name-Real' and 'Name-Email', as these are
automatically added.""")

    gnupg_keyserver = django.db.models.CharField(
        max_length=200,
        default="subkeys.pgp.net",
        help_text="GnuPG keyserver to use (as fill-in helper).")

    ftpd_bind = django.db.models.CharField(
        max_length=200,
        default="0.0.0.0:8067",
        help_text="FTP Server IP/Hostname and port to bind to.")

    ftpd_options = django.db.models.CharField(max_length=255, default="", blank=True, help_text="For future use.")

    # Load options
    build_queue_size = django.db.models.IntegerField(
        default=mini_buildd.misc.get_cpus(),
        help_text="Maximum number of parallel builds.")

    sbuild_jobs = django.db.models.IntegerField(
        default=1,
        help_text="Degree of parallelism per build (via sbuild's '--jobs' option).")

    # EMail options
    smtp_server = django.db.models.CharField(
        max_length=254,
        default="{h}:25".format(h=socket.getfqdn()),
        help_text="SMTP server (and optionally port) for mail sending.")

    notify = django.db.models.ManyToManyField(mini_buildd.models.repository.EmailAddress, blank=True)
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

    custom_hooks_directory = django.db.models.CharField(max_length=255, default="", blank=True, help_text="For future use.")

    show_last_packages = django.db.models.IntegerField(
        default=30,
        help_text="How many last packages to show in status.")
    show_last_builds = django.db.models.IntegerField(
        default=30,
        help_text="How many last builds to show in status.")

    wait_for_build_results = django.db.models.IntegerField(
        default=5,
        help_text="Future use: How many days to wait for build results until finishing a package.")
    keep_build_results = django.db.models.IntegerField(
        default=5,
        help_text="Future use: How many days to keep build results that cannot be uploaded.")

    class Meta(mini_buildd.models.base.StatusModel.Meta):
        verbose_name_plural = "Daemon"

    class Admin(mini_buildd.models.base.StatusModel.Admin):
        fieldsets = (
            (None, {"fields": (), "description": """\
The daemon instance. There is always exactly one instance of this.

prepare/unprepare actions will generate/remove the GnuPG key.

activate/deactivate actions will start/stop the 'daemon'.
"""}),
            ("Archive identity", {"fields": (("identity", "hostname", "email_address"), "gnupg_template")}),
            ("FTP (incoming) Options", {"fields": ("ftpd_bind", "ftpd_options")}),
            ("Load Options", {"fields": ("build_queue_size", "sbuild_jobs")}),
            ("E-Mail Options", {"fields": ("smtp_server", "notify", "allow_emails_to")}),
            ("Other Options", {"fields": ("gnupg_keyserver", "custom_hooks_directory", "show_last_packages", "show_last_builds")}))

    def __unicode__(self):
        return "{i}: Serving {r} repositories, {c} chroots, {R} remotes ({s})".format(
            i=self.identity,
            r=len(mini_buildd.models.repository.Repository.mbd_get_active()),
            c=len(mini_buildd.models.chroot.Chroot.mbd_get_active()),
            R=len(mini_buildd.models.gnupg.Remote.mbd_get_active()),
            s=self.mbd_get_status_display())

    def __init__(self, *args, **kwargs):
        super(Daemon, self).__init__(*args, **kwargs)
        self._mbd_fullname = "mini-buildd archive {i}".format(i=self.identity)
        self._mbd_gnupg = mini_buildd.gnupg.GnuPG(self.gnupg_template, self._mbd_fullname, self.email_address)
        self._mbd_gnupg_long_id = self._mbd_gnupg.get_first_sec_key_long_id()
        self._mbd_gnupg_fingerprint = self._mbd_gnupg.get_first_sec_key_fingerprint()

    @property
    def mbd_fullname(self):
        return self._mbd_fullname

    @property
    def mbd_gnupg(self):
        return self._mbd_gnupg

    @property
    def mbd_gnupg_fingerprint(self):
        return self._mbd_gnupg_fingerprint

    @property
    def mbd_gnupg_long_id(self):
        return self._mbd_gnupg_long_id

    def clean(self, *args, **kwargs):
        super(Daemon, self).clean(*args, **kwargs)

        self.mbd_validate_regex(r"^[a-zA-Z0-9\-]+$", self.identity, "Identity")

        if Daemon.objects.count() > 0 and self.id != Daemon.objects.get().id:
            raise django.core.exceptions.ValidationError("You can only create one Daemon instance!")

    def mbd_prepare(self, request):
        self._mbd_gnupg.prepare()
        self._mbd_gnupg_long_id = self._mbd_gnupg.get_first_sec_key_long_id()
        self._mbd_gnupg_fingerprint = self._mbd_gnupg.get_first_sec_key_fingerprint()
        self.mbd_msg_info(request, "Daemon GnuPG key generated: {i}: {f}".format(i=self._mbd_gnupg_long_id, f=self._mbd_gnupg_fingerprint))

    def mbd_unprepare(self, request):
        self._mbd_gnupg.unprepare()
        self.mbd_msg_info(request, "Daemon GnuPG key removed.")

# pylint: disable=R0201
    def mbd_check(self, request):
        """
        Try-run checks on active and auto-reactivateable repos, chroots and remotes.
        This possibly automatically (de-)activates objects.
        """
        mini_buildd.models.repository.Repository.Admin.mbd_action(
            request,
            mini_buildd.models.repository.Repository.mbd_get_active_or_auto_reactivate(),
            "check")

        mini_buildd.models.chroot.Chroot.Admin.mbd_action(
            request,
            mini_buildd.models.chroot.Chroot.mbd_get_active_or_auto_reactivate(),
            "check")

        mini_buildd.models.gnupg.Remote.Admin.mbd_action(
            request,
            mini_buildd.models.gnupg.Remote.mbd_get_active_or_auto_reactivate(),
            "check")

        if not mini_buildd.models.repository.Repository.mbd_get_active() and not mini_buildd.models.chroot.Chroot.mbd_get_active():
            raise Exception("At least one chroot or repository must be active to start the daemon.")
# pylint: enable=R0201

    def mbd_activate(self, request):
        self.mbd_get_daemon().restart(activate_action=True, request=request)

    def mbd_deactivate(self, request):
        self.mbd_get_daemon().stop(request=request)

    def mbd_get_ftp_hopo(self):
        return mini_buildd.misc.HoPo("{h}:{p}".format(h=self.hostname, p=mini_buildd.misc.HoPo(self.ftpd_bind).port))

    def mbd_get_ftp_url(self):
        return "ftp://{h}".format(h=self.mbd_get_ftp_hopo().string)

    def mbd_get_http_hopo(self):
        return mini_buildd.misc.HoPo("{h}:{p}".format(h=self.hostname, p=mini_buildd.misc.HoPo(mini_buildd.setup.HTTPD_BIND).port))

    def mbd_get_http_url(self):
        return "http://{h}/".format(h=self.mbd_get_http_hopo().string)

    def mbd_get_archive_origin(self):
        return "Mini-Buildd archive {i} on {h}".format(i=self.identity, h=self.hostname)

    def mbd_get_pub_key(self):
        return self._mbd_gnupg.get_pub_key()

    def mbd_get_dput_conf(self):
        return """\
[mini-buildd-{i}]
method   = ftp
fqdn     = {h}
login    = anonymous
incoming = /incoming
""".format(i=self.identity, h=self.mbd_get_ftp_hopo().string)

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
                maintainer = changes.get("Maintainer")
                if repository.notify_maintainer and maintainer:
                    add_to(email.utils.parseaddr(maintainer)[1])
                changed_by = changes.get("Changed-By")
                if repository.notify_changed_by and changed_by:
                    add_to(email.utils.parseaddr(changed_by)[1])

        if m_to:
            try:
                body['Subject'] = subject
                body['From'] = m_from
                body['To'] = ", ".join(m_to)

                hopo = mini_buildd.misc.HoPo(self.smtp_server)
                s = smtplib.SMTP(hopo.host, hopo.port)
                s.sendmail(m_from, m_to, body.as_string())
                s.quit()
                LOG.info("Sent: Mail '{s}' to '{r}'".format(s=subject, r=m_to))
            except Exception as e:
                mini_buildd.setup.log_exception(LOG, "Mail sending failed: '{s}' to '{r}'".format(s=subject, r=m_to), e)
        else:
            LOG.warn("No email addresses found, skipping: {s}".format(s=subject))
