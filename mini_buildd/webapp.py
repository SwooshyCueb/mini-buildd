# -*- coding: utf-8 -*-
import os
import logging
import random

import django.conf
import django.core.handlers.wsgi
import django.core.management
import django.contrib.auth

import mini_buildd.setup
import mini_buildd.compat08x
import mini_buildd.models

LOG = logging.getLogger(__name__)


class WebApp(django.core.handlers.wsgi.WSGIHandler):
    """
    This class represents mini-buildd's web application.
    """

    def __init__(self):
        LOG.info("Configuring && generating django app...")
        super(WebApp, self).__init__()

        django.conf.settings.configure(
            DEBUG="django" in mini_buildd.setup.DEBUG,
            TEMPLATE_DEBUG="django" in mini_buildd.setup.DEBUG,

            TEMPLATE_DIRS=['/usr/share/pyshared/mini_buildd/templates'],
            TEMPLATE_LOADERS=(
                'django.template.loaders.filesystem.Loader',
                'django.template.loaders.app_directories.Loader'),

            DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3',
                                   'NAME': os.path.join(mini_buildd.setup.HOME_DIR, "config.sqlite")}},

            TIME_ZONE=None,
            USE_L10N=True,
            SECRET_KEY=self.get_django_secret_key(mini_buildd.setup.HOME_DIR),
            ROOT_URLCONF='mini_buildd.root_urls',
            STATIC_URL="/static/",
            AUTH_PROFILE_MODULE='mini_buildd.Uploader',
            INSTALLED_APPS=(
                'django.contrib.auth',
                'django.contrib.contenttypes',
                'django.contrib.admin',
                'django.contrib.sessions',
                'django.contrib.admindocs',
                'django_extensions',
                'mini_buildd'))

        mini_buildd.models.import_all()
        self.syncdb()
        self.setup_default_models()

    @classmethod
    def setup_default_models(cls):
        import mini_buildd.models.repository

        default_layout, created = mini_buildd.models.repository.Layout.objects.get_or_create(name="Default")
        if created:
            stable, created = mini_buildd.models.repository.Suite.objects.get_or_create(name="stable", uploadable=False)
            testing, created = mini_buildd.models.repository.Suite.objects.get_or_create(name="testing", uploadable=False, migrates_to=stable)
            unstable, created = mini_buildd.models.repository.Suite.objects.get_or_create(name="unstable", migrates_to=testing)
            experimental, created = mini_buildd.models.repository.Suite.objects.get_or_create(name="experimental", experimental=True)

            default_layout.suites.add(stable)
            default_layout.suites.add(testing)
            default_layout.suites.add(unstable)
            default_layout.suites.add(experimental)

            default_layout.build_keyring_package_for.add(unstable)
            default_layout.save()

    @classmethod
    def set_admin_password(cls, password):
        """
        This method sets the password for the administrator.

        :param password: The password to use.
        :type password: string
        """

        try:
            user = django.contrib.auth.models.User.objects.get(username='admin')
            LOG.info("Updating 'admin' user password...")
            user.set_password(password)
            user.save()
        except django.contrib.auth.models.User.DoesNotExist:
            LOG.info("Creating initial 'admin' user...")
            django.contrib.auth.models.User.objects.create_superuser('admin', 'root@localhost', password)

    @classmethod
    def unprepare(cls, models):
        """
        .. todo:: Update to new model scheme!!

        Unprepare all given (status) models.
        """
        import mini_buildd.models
        for m in models:
            model_class = getattr(mini_buildd.models, m)
            for o in model_class.objects.all():
                model_class.Admin.action(None, (o,), "unprepare", model_class.STATUS_UNPREPARED, min)

    @classmethod
    def syncdb(cls):
        LOG.info("Syncing database...")
        django.core.management.call_command('syncdb', interactive=False, verbosity=0)

    @classmethod
    def loaddata(cls, file_name):
        if os.path.splitext(file_name)[1] == ".conf":
            LOG.info("Try loading ad 08x.conf: {f}".format(f=file_name))
            mini_buildd.compat08x.import_conf(file_name)
        else:
            django.core.management.call_command('loaddata', file_name)

    @classmethod
    def dumpdata(cls, app_path):
        LOG.info("Dumping data for: {a}".format(a=app_path))
        django.core.management.call_command('dumpdata', app_path, indent=2, format='json')

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
            secret_key = ''.join([random.choice('abcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*(-_=+)') for _i in range(50)])
            secret_key_fd = os.open(secret_key_filename, os.O_CREAT | os.O_WRONLY, 0600)
            os.write(secret_key_fd, secret_key)
            os.close(secret_key_fd)
        else:
            existing_file = open(secret_key_filename, "r")
            secret_key = existing_file.read()
            existing_file.close()

        return secret_key
