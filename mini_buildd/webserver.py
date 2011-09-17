# coding: utf-8
import os
import sys

import wsgiref.simple_server

from django.conf import settings
import django.core.handlers.wsgi
from django.core.management import call_command

from mini_buildd.log import log
from mini_buildd.options import opts

import mini_buildd.compat08x

class Django():
    def __init__(self, debug=False):
        log.info("Configuring && generating django app...")
        self._django = django.core.handlers.wsgi.WSGIHandler()
        settings.configure(
            DEBUG = debug,
            TEMPLATE_DEBUG = debug,

            # @todo: Seems this is needed for admin/doc.
            SITE_ID = 1,

            DATABASES =
            {
                'default':
                    {
                    'ENGINE': 'django.db.backends.sqlite3',
                    'NAME': opts.home + '/web/config.sqlite',
                    }
                },
            TIME_ZONE = None,
            USE_L10N = True,
            SECRET_KEY = ')-%wqspscru#-9rl6u0sbbd*yn@$=ic^)-9c$+@@w898co2!7^',
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

    def syncdb(self):
        log.info("Syncing database...")
        call_command('syncdb', interactive=False)

    def loaddata(self, f):
        if os.path.splitext(f)[1] == ".conf":
            log.info("Try loading ad 08x.conf: {f}".format(f=f))
            mini_buildd.compat08x.importConf(f)
        else:
            prefix = "" if f[0] == "/" else opts.instdir + "/mini_buildd/fixtures/"
            call_command('loaddata', prefix  + f)

    def dumpdata(self, a):
        log.info("Dumping data for: {a}".format(a=a))
        if a == "08x":
            mini_buildd.compat08x.exportConf("/dev/stdout")
        else:
            call_command('dumpdata', a, indent=2, format="json")

class WebServer():
    def __init__(self, django, host='', port=8080):
        # Http server app
        log.info("Starting wsgi web server: '%s:%s'." % (host, port))
        self._httpd = wsgiref.simple_server.make_server(host, port, django)

    def run(self):
        self._httpd.serve_forever()
