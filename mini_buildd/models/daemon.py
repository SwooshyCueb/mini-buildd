# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import re
import socket
import email.utils
import logging

import django.db
import django.core.exceptions
import django.core.mail
import django.contrib.auth.models

import mini_buildd.misc
import mini_buildd.changes
import mini_buildd.gnupg
import mini_buildd.builder

import mini_buildd.models.base
import mini_buildd.models.repository
import mini_buildd.models.chroot
import mini_buildd.models.gnupg

from mini_buildd.models.msglog import MsgLog
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
    gnupg_template = django.db.models.TextField(default="""\
Key-Type: RSA
Key-Length: 4096
Expire-Date: 0
""", help_text="""
Template as accepted by 'gpg --batch --gen-key' (see 'man gpg').

You should not give 'Name-Real' and 'Name-Email', as these are
automatically added.""")

    gnupg_keyserver = django.db.models.CharField(
        max_length=200,
        default="pool.sks-keyservers.net",
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
    # DEPRECTATED/UNUSED: With the switch to django mail framework, this is now configured via the --smtp command line argument.
    smtp_server = django.db.models.CharField(
        max_length=254,
        default="localhost:25",
        help_text="DEPRECATED/UNUSED: Replaced by '--smtp' command line option.")

    notify = django.db.models.ManyToManyField(mini_buildd.models.repository.EmailAddress,
                                              blank=True,
                                              help_text="Addresses that get all notification emails unconditionally.")
    allow_emails_to = django.db.models.CharField(
        max_length=254,
        default=".*@{h}".format(h=socket.getfqdn()),
        help_text="""\
Regex to allow sending emails to automatically computed
addresses (currently the 'Changed-By' or 'Maintainer' addresses
when this feature is enabled for the resp. repository).

Use '.*' to allow all -- it's however recommended to put this to
s.th. like '.*@myemail.domain', to avoid original package
maintainers to be accidentially spammed.
""")

    custom_hooks_directory = django.db.models.CharField(max_length=255, default="", blank=True, help_text="For future use.")

    show_last_packages = django.db.models.IntegerField(
        default=100,
        help_text="How many 'last packages' data to keep for the status display.")
    show_last_builds = django.db.models.IntegerField(
        default=100,
        help_text="How many 'last builds' data to keep for the status display.")

    wait_for_build_results = django.db.models.IntegerField(
        default=5,
        help_text="Future use: How many days to wait for build results until finishing a package.")
    keep_build_results = django.db.models.IntegerField(
        default=5,
        help_text="Future use: How many days to keep build results that cannot be uploaded.")

    LETHAL_DEPENDENCIES = False

    class Meta(mini_buildd.models.base.StatusModel.Meta):
        verbose_name_plural = "Daemon"

    class Admin(mini_buildd.models.base.StatusModel.Admin):
        fieldsets = (
            (None, {"fields": (), "description": """\
The daemon instance. There is always exactly one instance of this.

prepare/remove actions will generate/remove the GnuPG key.
"""}),
            ("Archive identity", {"fields": (("identity", "hostname", "email_address"), "gnupg_template")}),
            ("FTP (incoming) Options", {"fields": ("ftpd_bind", "ftpd_options")}),
            ("Load Options", {"fields": ("build_queue_size", "sbuild_jobs")}),
            ("E-Mail Options", {"fields": ("smtp_server", "notify", "allow_emails_to")}),
            ("Other Options", {"fields": ("gnupg_keyserver", "custom_hooks_directory", "show_last_packages", "show_last_builds")}))

        filter_horizontal = ("notify",)

        # These are depcrecated or not used yet
        readonly_fields = ["smtp_server", "ftpd_options", "custom_hooks_directory"]

        def save_model(self, request, obj, form, change):
            "Always update date the daemon object to model."
            obj.mbd_get_daemon().update_to_model(obj)
            super(Daemon.Admin, self).save_model(request, obj, form, change)

    def __unicode__(self):
        return "{i}: Serving {r} repositories, {c} chroots, using {R} remotes".format(
            i=self.identity,
            r=len(mini_buildd.models.repository.Repository.mbd_get_active()),
            c=len(mini_buildd.models.chroot.Chroot.mbd_get_active()),
            R=len(mini_buildd.models.gnupg.Remote.mbd_get_active()))

    def __init__(self, *args, **kwargs):
        super(Daemon, self).__init__(*args, **kwargs)
        self._mbd_fullname = "mini-buildd archive {i}".format(i=self.identity)
        self._mbd_gnupg = mini_buildd.gnupg.GnuPG(self.gnupg_template, self._mbd_fullname, self.email_address)
        self._mbd_gnupg_long_id = self._mbd_gnupg.get_first_sec_key().key_id
        self._mbd_gnupg_fingerprint = self._mbd_gnupg.get_first_sec_key_fingerprint().user_id

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
        self._mbd_gnupg_long_id = self._mbd_gnupg.get_first_sec_key().key_id
        self._mbd_gnupg_fingerprint = self._mbd_gnupg.get_first_sec_key_fingerprint().user_id
        MsgLog(LOG, request).info("Daemon GnuPG key generated: {i}: {f}".format(i=self._mbd_gnupg_long_id, f=self._mbd_gnupg_fingerprint))

    @classmethod
    def mbd_sync(cls, request):
        MsgLog(LOG, request).warn("The GnuPG key will never be updated automatically. Explicitly run remove+prepare to achieve this.")

    def mbd_remove(self, request):
        self._mbd_gnupg.remove()
        MsgLog(LOG, request).info("Daemon GnuPG key removed.")

    def mbd_get_dependencies(self):
        "All active or to-be active repositories, remotes and chroots."
        result = []
        for model in [mini_buildd.models.repository.Repository, mini_buildd.models.chroot.Chroot, mini_buildd.models.gnupg.Remote]:
            for o in model.mbd_get_active_or_auto_reactivate():
                result.append(o)
        return result

    def mbd_check(self, request):
        "Just warn in case there are no repos and no chroots."
        if not self.mbd_get_daemon().get_active_repositories() and not self.mbd_get_daemon().get_active_chroots():
            MsgLog(LOG, request).warn("No active chroot or repository.")

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
# These currently only help for mini-buildd-tool bash autocompletion
x_mini_buildd_host = {H}
x_mini_buildd_users =
""".format(i=self.identity, h=self.mbd_get_ftp_hopo().string, H=self.mbd_get_http_hopo().string)

    def _mbd_notify_signature(self, typ):
        reason = {"daemon": "Your address is configured to get any notifications (contact administrators if you don't want this).",
                  "repository": "Your address is configured to get any notifications for this repository (contact administrators if you don't want this).",
                  "changed-by": "Your address is the uploader of the package ('Changed-By' in changes).",
                  "maintainer": "Your address is the maintainer of the package ('Maintainer' in changes).",
                  "subscriber": "Your user account has a matching subscription.",
                  }.get(typ, "Unknown")
        # pylint: disable=W1402
        return """
--\N{SPACE}
mini-buildd instance '{id}' at {host} <{email}>
Reason for this mail: {reason}
Visit mini-buildd   : {url}
Manage your account : {url}accounts/login/
""".format(id=self.identity, host=self.hostname, email=self.email_address, reason=reason, url=self.mbd_get_http_url())

    def mbd_notify(self, subject, body, repository=None, changes=None, distribution=None, msglog=LOG):
        subject_prefix = "[mini-buildd-{i}] ".format(i=self.identity)
        m_to = []
        m_to_raw = []
        m_automatic_to_allow = re.compile(self.allow_emails_to)
        # Include all plain 'msglogs' so far
        m_msglog = getattr(msglog, "plain", "")
        if m_msglog:
            m_msglog = "Daemon messages:\n{msgs}---\n".format(msgs=m_msglog)

        def add_to(address, typ, is_automatic):
            address_raw = email.utils.parseaddr(address)[1]
            if not is_automatic or m_automatic_to_allow.search(address_raw):
                if address_raw in m_to_raw:
                    msglog.debug("Notify: Skipping {t} address: {a}: Duplicate".format(t=typ, a=address))
                else:
                    m_to.append((subject_prefix + subject, m_msglog + body + self._mbd_notify_signature(typ), self.email_address, [address]))
                    m_to_raw.append(address_raw)
                    msglog.info("Notify: Adding {t} address: {a}".format(t=typ, a=address))
            else:
                msglog.warn("Notify: Skipping {t} address: {a}: Not allowed (only '{r}')".format(t=typ, a=address, r=self.allow_emails_to))

        def get_subscriptions():
            package = changes.get("Source", None)
            real_distribution = distribution
            if real_distribution is None:
                # If distribution was not given explicitely, try from changes, resolving meta dists if needed.
                changes_dist = changes.get("Distribution", "")
                real_distribution = mini_buildd.models.repository.get_meta_distribution_map().get(changes_dist, changes_dist)
            return self.mbd_get_daemon().get_subscription_objects().filter(package__in=[package, ""], distribution__in=[real_distribution, ""])

        # Add hardcoded addresses from daemon
        for m in self.notify.all():
            add_to(m.__unicode__(), "daemon", is_automatic=False)

        # Add hardcoded addresses from repository
        if repository:
            for m in repository.notify.all():
                add_to(m.__unicode__(), "repository", is_automatic=False)

        if changes:
            # Add package uploader (Changed-By): Add even if we do not have a repo, so uploader is informed on such error cases too.
            changed_by = changes.get("X-Mini-Buildd-Originally-Changed-By", changes.get("Changed-By"))
            if not repository or (repository.notify_changed_by and changed_by):
                add_to(changed_by, "changed-by", is_automatic=True)

            # Add package maintainer: Add only when we have a repo, and it's configured to do so
            maintainer = changes.get("Maintainer")
            if repository and (repository.notify_maintainer and maintainer):
                add_to(maintainer, "maintainer", is_automatic=True)

            # Add user subscriptions
            for s in get_subscriptions():
                address = "{n} <{a}>".format(n=s.subscriber.get_full_name(), a=s.subscriber.email)
                if s.subscriber.is_active:
                    add_to(address, "subscriber", is_automatic=False)
                else:
                    msglog.debug("Notify: Skipping subscription address: {a}: Account disabled".format(a=address, r=self.allow_emails_to))

        try:
            django.core.mail.send_mass_mail(m_to)
            msglog.info("Notify: Sent '{s}'".format(s=subject))
        except Exception as e:
            mini_buildd.setup.log_exception(msglog, "Notify: Mail '{s}' failed to '{r}'".format(s=subject, r=m_to), e)
