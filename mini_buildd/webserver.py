# coding: utf-8
import wsgiref.simple_server
import django.core.management

import mini_buildd

class WebServerBase(object):
    def __init__(self, django):
        bind = mini_buildd.opts.bind.split(":")
        self._host = bind[0]
        self._port = int(bind[1])
        self._django = django

class WsgiRefWebServer(WebServerBase):
    def __init__(self, django):
        super(WsgiRefWebServer, self).__init__(django)
        self._httpd = wsgiref.simple_server.make_server(self._host, self._port, self._django)

    def run(self):
        mini_buildd.log.info("Starting WSGIRef web server: '{b}'.".format(b=mini_buildd.opts.bind))
        self._httpd.serve_forever()

class DjangoWebServer(WebServerBase):
    def __init__(self, django):
        super(DjangoWebServer, self).__init__(django)

    def run(self):
        mini_buildd.log.warn("Running django development server...")
        django.core.management.call_command('runserver', self._host + ":" + str(self._port))

# Set web server to be used
WebServer = WsgiRefWebServer
#WebServer = DjangoWebServer
