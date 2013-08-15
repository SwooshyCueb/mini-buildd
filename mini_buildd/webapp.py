# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import logging
import random

import django.conf
import django.core.handlers.wsgi
import django.core.management
import django.contrib.messages.constants

import mini_buildd.setup
import mini_buildd.models
import mini_buildd.models.msglog

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

    def __init__(self, smtp_string, loglevel):
        LOG.info("Configuring && generating django app...")
        super(WebApp, self).__init__()

        smtp = SMTPCreds(smtp_string)
        debug = "webapp" in mini_buildd.setup.DEBUG
        django.conf.settings.configure(
            DEBUG=debug,
            TEMPLATE_DEBUG=debug,
            MESSAGE_LEVEL=mini_buildd.models.msglog.MsgLog.level2django(loglevel),

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

    @classmethod
    def set_admin_password(cls, password):
        """
        This method sets the password for the administrator.

        :param password: The password to use.
        :type password: string
        """
        # This import needs the django app to be already configured (since django 1.5.2)
        import django.contrib.auth

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
        # This import needs the django app to be already configured
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
