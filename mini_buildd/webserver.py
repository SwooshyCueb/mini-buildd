# coding: utf-8
import os
import sys

import wsgiref.simple_server
import django.core.handlers.wsgi

from mini_buildd.log import log

class WebServer():
    def __init__(self, host='', port=8080):
        # Django app (make sure DJANGO_SETTINGS is set correctly)
        self._django = django.core.handlers.wsgi.WSGIHandler()

        # Http server app
        self._httpd = wsgiref.simple_server.make_server(host, port, self._django)
        log.info("WebServer: '%s:%s'." % (host, port))

    def run(self):
        self._httpd.serve_forever()
