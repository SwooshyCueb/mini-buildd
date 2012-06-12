# -*- coding: utf-8 -*-
import os, logging, random

import django.conf, django.core.handlers.wsgi, django.core.management

from mini_buildd import setup, misc, compat08x

log = logging.getLogger(__name__)

class WebApp(django.core.handlers.wsgi.WSGIHandler):
    """
    This class represents mini-buildd's web application.
    """

    def __init__(self, home):
        ".. todo:: Maybe useful later when we fix up static files."
        if int(django.VERSION[1]) >= 4:
            static_admin_dir = "/usr/share/pyshared/django/contrib/admin/static/"
        else:
            static_admin_dir = "/usr/share/pyshared/django/contrib/admin/media/"

        log.info("Configuring && generating django app...")
        super(WebApp, self).__init__()

        django.conf.settings.configure(
            DEBUG = setup.DEBUG,
            TEMPLATE_DEBUG = setup.DEBUG,

            DATABASES =
            {
                'default':
                    {
                    'ENGINE': 'django.db.backends.sqlite3',
                    'NAME': os.path.join(home, "config.sqlite"),
                    }
                },
            TIME_ZONE = None,
            USE_L10N = True,
            SECRET_KEY = self.get_django_secret_key(home),
            ROOT_URLCONF = 'mini_buildd.root_urls',
            STATIC_URL = "/static/",
            STATICFILES_DIRS = ( static_admin_dir, ),
            INSTALLED_APPS = (
                'django.contrib.auth',
                'django.contrib.contenttypes',
                'django.contrib.admin',
                'django.contrib.sessions',
                'django.contrib.admindocs',
                'django.contrib.staticfiles',
                'django_extensions',
                'mini_buildd'
                ))
        self.syncdb()
        self.setup_default_models()

    def setup_default_models(self):
        from mini_buildd import models
        l, created = models.Layout.objects.get_or_create(name="Default")
        if created:
            e, created = models.Suite.objects.get_or_create(name="experimental", mandatory_version="~{rid}{nbv}+0")
            u, created = models.Suite.objects.get_or_create(name="unstable")
            t, created = models.Suite.objects.get_or_create(name="testing", migrates_from=u)
            s, created = models.Suite.objects.get_or_create(name="stable", migrates_from=t)
            l.suites.add(e)
            l.suites.add(u)
            l.suites.add(t)
            l.suites.add(s)
            l.save()

        codename = misc.call(["lsb_release", "--short", "--codename"], value_on_error="sid").strip()
        s, created = models.Source.objects.get_or_create(origin="Debian", codename=codename)
        d, created = models.Distribution.objects.get_or_create(base_source=s)

    def set_admin_password(self, password):
        """
        This method sets the password for the administrator.

        :param password: The password to use.
        :type password: string
        """

        import django.contrib.auth.models
        try:
            user = django.contrib.auth.models.User.objects.get(username='admin')
            log.info("Updating 'admin' user password...")
            user.set_password(password)
            user.save()
        except django.contrib.auth.models.User.DoesNotExist:
            log.info("Creating initial 'admin' user...")
            django.contrib.auth.models.User.objects.create_superuser('admin', 'root@localhost', password)

    def syncdb(self):
        log.info("Syncing database...")
        django.core.management.call_command('syncdb', interactive=False, verbosity=0)

    def collectstatic(self):
        ".. todo:: Maybe useful later when we fix up static files."
        log.info("Collecting static data...")
        django.core.management.call_command('collectstatic', interactive=False, verbosity=2)

    def loaddata(self, f):
        if os.path.splitext(f)[1] == ".conf":
            log.info("Try loading ad 08x.conf: {f}".format(f=f))
            compat08x.importConf(f)
        else:
            django.core.management.call_command('loaddata', f)

    def dumpdata(self, a):
        log.info("Dumping data for: {a}".format(a=a))
        if a == "08x":
            compat08x.exportConf("/dev/stdout")
        else:
            django.core.management.call_command('dumpdata', a, indent=2, format='json')

    def get_django_secret_key(self, home):
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
            secret_key = ''.join([random.choice('abcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*(-_=+)') for i in range(50)])
            secret_key_fd = os.open(secret_key_filename, os.O_CREAT | os.O_WRONLY, 0600)
            os.write(secret_key_fd, secret_key)
            os.close(secret_key_fd)
        else:
            existing_file = open(secret_key_filename, "r")
            secret_key = existing_file.read()
            existing_file.close()

        return secret_key
