# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import logging
import random

import django.conf
import django.core.handlers.wsgi
import django.core.management
import django.contrib.auth
import django.contrib.messages.constants

import mini_buildd.setup
import mini_buildd.models

LOG = logging.getLogger(__name__)


class SMTPCreds(object):
    """
    SMTP creds string parser. Format "USER:PASSWORD@smtp|ssmtp://HOST:PORT".

    >>> d = SMTPCreds(":@smtp://localhost:25")
    >>> (d.user, d.password, d.protocol, d.host, d.port)
    (u'', u'', u'smtp', u'localhost', 25)
    >>> d = SMTPCreds("kuh:sa:ck@smtp://colahost:44")
    >>> (d.user, d.password, d.protocol, d.host, d.port)
    (u'kuh', u'sa:ck', u'smtp', u'colahost', 44)
    """
    def __init__(self, creds):
        self.creds = creds
        at = creds.partition("@")

        usrpass = at[0].partition(":")
        self.user = usrpass[0]
        self.password = usrpass[2]

        smtp = at[2].partition(":")
        self.protocol = smtp[0]

        hopo = smtp[2].partition(":")
        self.host = hopo[0][2:]
        self.port = int(hopo[2])


class WebApp(django.core.handlers.wsgi.WSGIHandler):
    """
    This class represents mini-buildd's web application.
    """

    def __init__(self, smtp_string):
        LOG.info("Configuring && generating django app...")
        super(WebApp, self).__init__()

        smtp = SMTPCreds(smtp_string)
        debug = "django" in mini_buildd.setup.DEBUG
        django.conf.settings.configure(
            DEBUG=debug,
            TEMPLATE_DEBUG=debug,
            MESSAGE_LEVEL=django.contrib.messages.constants.DEBUG if debug else django.contrib.messages.constants.INFO,

            ALLOWED_HOSTS=["*"],

            EMAIL_HOST=smtp.host,
            EMAIL_PORT=smtp.port,
            EMAIL_USE_TLS=smtp.protocol == "ssmtp",
            EMAIL_HOST_USER=smtp.user,
            EMAIL_HOST_PASSWORD=smtp.password,

            TEMPLATE_DIRS=["/usr/share/pyshared/mini_buildd/templates"],
            TEMPLATE_LOADERS=(
                "django.template.loaders.filesystem.Loader",
                "django.template.loaders.app_directories.Loader"),

            DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3",
                                   "NAME": os.path.join(mini_buildd.setup.HOME_DIR, "config.sqlite")}},

            TIME_ZONE=None,
            USE_L10N=True,
            SECRET_KEY=self.get_django_secret_key(mini_buildd.setup.HOME_DIR),
            ROOT_URLCONF="mini_buildd.root_urls",
            STATIC_URL="/static/",
            AUTH_PROFILE_MODULE="mini_buildd.Uploader",
            ACCOUNT_ACTIVATION_DAYS=3,
            LOGIN_REDIRECT_URL="/mini_buildd/",
            INSTALLED_APPS=(
                "django.contrib.auth",
                "django.contrib.contenttypes",
                "django.contrib.admin",
                "django.contrib.sessions",
                "django.contrib.admindocs",
                "django_extensions",
                "registration",
                "mini_buildd"))

        mini_buildd.models.import_all()
        self._syncdb()
        self._default_setup()

    @classmethod
    def _default_setup(cls):
        """
        Create default suites and layout unless it already exists.
        """
        import mini_buildd.models.repository

        stable, created = mini_buildd.models.repository.Suite.objects.get_or_create(name="stable")
        testing, created = mini_buildd.models.repository.Suite.objects.get_or_create(name="testing")
        unstable, created = mini_buildd.models.repository.Suite.objects.get_or_create(name="unstable")
        snapshot, created = mini_buildd.models.repository.Suite.objects.get_or_create(name="snapshot")
        experimental, created = mini_buildd.models.repository.Suite.objects.get_or_create(name="experimental")

        for name, extra_options in {"Default": {"stable": "Rollback: 6\n",
                                                "testing": "Rollback: 3\n",
                                                "unstable": "Rollback: 9\n",
                                                "snapshot": "Rollback: 12\n",
                                                "experimental": "Rollback: 6\n"},
                                    "Default (no rollbacks)": {}}.items():

            default_layout, created = mini_buildd.models.repository.Layout.objects.get_or_create(name=name)
            if created:
                so_stable = mini_buildd.models.repository.SuiteOption(
                    layout=default_layout,
                    suite=stable,
                    uploadable=False,
                    extra_options=extra_options.get("stable", ""))
                so_stable.save()

                so_testing = mini_buildd.models.repository.SuiteOption(
                    layout=default_layout,
                    suite=testing,
                    uploadable=False,
                    migrates_to=so_stable,
                    extra_options=extra_options.get("testing", ""))
                so_testing.save()

                so_unstable = mini_buildd.models.repository.SuiteOption(
                    layout=default_layout,
                    suite=unstable,
                    migrates_to=so_testing,
                    build_keyring_package=True,
                    extra_options=extra_options.get("unstable", ""))
                so_unstable.save()

                so_snapshot = mini_buildd.models.repository.SuiteOption(
                    layout=default_layout,
                    suite=snapshot,
                    experimental=True,
                    extra_options=extra_options.get("snapshot", ""))
                so_snapshot.save()

                so_experimental = mini_buildd.models.repository.SuiteOption(
                    layout=default_layout,
                    suite=experimental,
                    experimental=True,
                    but_automatic_upgrades=False,
                    extra_options=extra_options.get("experimental", ""))
                so_experimental.save()

        # Debian Developer layout
        debdev_layout, created = mini_buildd.models.repository.Layout.objects.get_or_create(
            name="Debian Developer",
            defaults={"mandatory_version_regex": ".*",
                      "experimental_mandatory_version_regex": ".*",
                      "extra_options": "Meta-Distributions: stable=squeeze-unstable unstable=sid-unstable experimental=sid-experimental\n"})

        if created:
            debdev_unstable = mini_buildd.models.repository.SuiteOption(
                layout=debdev_layout,
                suite=unstable,
                build_keyring_package=True)
            debdev_unstable.save()

            debdev_experimental = mini_buildd.models.repository.SuiteOption(
                layout=debdev_layout,
                suite=experimental,
                uploadable=True,
                experimental=True,
                but_automatic_upgrades=False)
            debdev_experimental.save()

    @classmethod
    def set_admin_password(cls, password):
        """
        This method sets the password for the administrator.

        :param password: The password to use.
        :type password: string
        """

        try:
            user = django.contrib.auth.models.User.objects.get(username="admin")
            LOG.info("Updating 'admin' user password...")
            user.set_password(password)
            user.save()
        except django.contrib.auth.models.User.DoesNotExist:
            LOG.info("Creating initial 'admin' user...")
            django.contrib.auth.models.User.objects.create_superuser("admin", "root@localhost", password)

    @classmethod
    def remove_system_artifacts(cls):
        """
        Bulk-remove all model instances that might have
        produced cruft on the system (i.e., outside
        mini-buildd's home).
        """
        import mini_buildd.models.chroot
        mini_buildd.models.chroot.Chroot.Admin.mbd_action(
            None,
            mini_buildd.models.chroot.Chroot.mbd_get_prepared(),
            "remove")

    @classmethod
    def _syncdb(cls):
        LOG.info("Syncing database...")
        django.core.management.call_command("syncdb", interactive=False, verbosity=0)
        django.core.management.call_command("cleanupregistration", interactive=False, verbosity=0)

    @classmethod
    def loaddata(cls, file_name):
        django.core.management.call_command("loaddata", file_name)

    @classmethod
    def dumpdata(cls, app_path):
        LOG.info("Dumping data for: {a}".format(a=app_path))
        django.core.management.call_command("dumpdata", app_path, indent=2, format="json")

    @classmethod
    def get_django_secret_key(cls, home):
        """
        This method creates *once* django's SECRET_KEY and/or returns it.

        :param home: mini-buildd's home directory.
        :type home: string
        :returns: string -- the (created) key.
        """

        secret_key_filename = os.path.join(home, ".django_secret_key")

        # the key to create or read from file
        secret_key = ""

        if not os.path.exists(secret_key_filename):
            # use same randomize-algorithm as in "django/core/management/commands/startproject.py"
            secret_key = "".join([random.choice("abcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*(-_=+)") for _i in range(50)])
            secret_key_fd = os.open(secret_key_filename, os.O_CREAT | os.O_WRONLY, 0600)
            os.write(secret_key_fd, secret_key)
            os.close(secret_key_fd)
        else:
            existing_file = open(secret_key_filename, "r")
            secret_key = existing_file.read()
            existing_file.close()

        return secret_key
