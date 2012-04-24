# -*- coding: utf-8 -*-
import os

import django.conf
import django.core.handlers.wsgi
import django.core.management

import mini_buildd

class WebApp(django.core.handlers.wsgi.WSGIHandler):
    def __init__(self, debug=False):
        mini_buildd.log.info("Configuring && generating django app...")
        super(WebApp, self).__init__()

        django.conf.settings.configure(
            DEBUG = debug,
            TEMPLATE_DEBUG = debug,

            # @todo: ? Seems this is needed for admin/doc.
            SITE_ID = 1,

            DATABASES =
            {
                'default':
                    {
                    'ENGINE': 'django.db.backends.sqlite3',
                    'NAME': os.path.join(mini_buildd.args.home, "config.sqlite"),
                    }
                },
            TIME_ZONE = None,
            USE_L10N = True,
            SECRET_KEY = ")-%wqspscru#-9rl6u0sbbd*yn@$=ic^)-9c$+@@w898co2!7^",
            ROOT_URLCONF = 'mini_buildd.root_urls',
            LOGGING_CONFIG = None,
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
        import django.contrib.auth.models
        try:
            user = django.contrib.auth.models.User.objects.get(username='admin')
            mini_buildd.log.info("Updating 'admin' user password...")
            user.set_password(password)
            user.save()
        except django.contrib.auth.models.User.DoesNotExist:
            mini_buildd.log.info("Creating initial 'admin' user...")
            django.contrib.auth.models.User.objects.create_superuser('admin', 'root@localhost', password)

    def create_default_config(self, mirror):
        mini_buildd.models.create_default(mirror)

    def syncdb(self):
        mini_buildd.log.info("Syncing database...")
        django.core.management.call_command('syncdb', interactive=False, verbosity=0)

    def loaddata(self, f):
        if os.path.splitext(f)[1] == ".conf":
            mini_buildd.log.info("Try loading ad 08x.conf: {f}".format(f=f))
            mini_buildd.compat08x.importConf(f)
        else:
            prefix = "" if f[0] == "/" else mini_buildd.args.instdir + "/mini_buildd/fixtures/"
            django.core.management.call_command('loaddata', prefix  + f)

    def dumpdata(self, a):
        mini_buildd.log.info("Dumping data for: {a}".format(a=a))
        if a == "08x":
            mini_buildd.compat08x.exportConf("/dev/stdout")
        else:
            django.core.management.call_command('dumpdata', a, indent=2, format='json')
