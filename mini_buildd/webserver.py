# coding: utf-8
import os
import sys

import wsgiref.simple_server

from django.conf import settings
import django.core.handlers.wsgi

from mini_buildd.log import log
from mini_buildd.options import opts

class WebServer():
    def __init__(self, host='', port=8080):
        settings.configure(
            # @todo: Always enable debug for now
            DEBUG = True,
            TEMPLATE_DEBUG = True,

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

        self._django = django.core.handlers.wsgi.WSGIHandler()

        # Http server app
        self._httpd = wsgiref.simple_server.make_server(host, port, self._django)
        log.info("WebServer: '%s:%s'." % (host, port))

    def run(self):
        self._httpd.serve_forever()
