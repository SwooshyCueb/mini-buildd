# coding: utf-8
import os
import sys

import wsgiref.simple_server

from django.conf import settings
import django.core.handlers.wsgi
from django.core.management import call_command

from mini_buildd.log import log
from mini_buildd.options import opts

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

    def loaddata(self, db=opts.import_db):
        log.info("Importing {db}".format(db=opts.import_db))
        call_command('loaddata', opts.instdir + "/mini_buildd/fixtures/" + opts.import_db)

    def dumpdata(self, f=opts.export_db):
        log.info("Exporting to file={f}".format(f=f))
        call_command('dumpdata', "mini_buildd", indent=2, format="json")

class WebServer():
    def __init__(self, django, host='', port=8080):
        # Http server app
        log.info("Starting wsgi web server: '%s:%s'." % (host, port))
        self._httpd = wsgiref.simple_server.make_server(host, port, django)

    def run(self):
        self._httpd.serve_forever()
