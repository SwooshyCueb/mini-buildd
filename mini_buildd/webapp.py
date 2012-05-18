# -*- coding: utf-8 -*-
import os

import django.conf
import django.core.handlers.wsgi
import django.core.management
import logging

import mini_buildd

log = logging.getLogger(__name__)

class WebApp(django.core.handlers.wsgi.WSGIHandler):
    """
    This class represents mini-buildd's web application.

    .. todo:: Django settings open questions

       - SITE_ID: ??? Seems this is needed for admin/doc.
       - SECRET_KEY: ??? wtf?
    """

    def __init__(self, home, instdir):
        log.info("Configuring && generating django app...")
        super(WebApp, self).__init__()
        self._instdir = instdir

        django.conf.settings.configure(
            DEBUG = mini_buildd.globals.DEBUG,
            TEMPLATE_DEBUG = mini_buildd.globals.DEBUG,

            SITE_ID = 1,

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
            SECRET_KEY = ")-%wqspscru#-9rl6u0sbbd*yn@$=ic^)-9c$+@@w898co2!7^",
            ROOT_URLCONF = 'mini_buildd.root_urls',
            INSTALLED_APPS = (
                'django.contrib.auth',
                'django.contrib.contenttypes',
                'django.contrib.admin',
                'django.contrib.sessions',
                'django.contrib.admindocs',
                'django_extensions',
                'mini_buildd'
                ))
        self.syncdb()

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

    def create_default_config(self, mirror):
        mini_buildd.models.create_default(mirror)

    def syncdb(self):
        log.info("Syncing database...")
        django.core.management.call_command('syncdb', interactive=False, verbosity=0)

    def loaddata(self, f):
        if os.path.splitext(f)[1] == ".conf":
            log.info("Try loading ad 08x.conf: {f}".format(f=f))
            mini_buildd.compat08x.importConf(f)
        else:
            prefix = "" if f[0] == "/" else self._instdir + "/mini_buildd/fixtures/"
            django.core.management.call_command('loaddata', prefix  + f)

    def dumpdata(self, a):
        log.info("Dumping data for: {a}".format(a=a))
        if a == "08x":
            mini_buildd.compat08x.exportConf("/dev/stdout")
        else:
            django.core.management.call_command('dumpdata', a, indent=2, format='json')
