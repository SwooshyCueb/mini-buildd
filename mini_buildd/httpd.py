# coding: utf-8
import mini_buildd
import logging

log = logging.getLogger(__name__)

class HttpDBase(object):
    def __init__(self, bind, wsgi_app):
        self._bind = bind.split(":")
        self._host = self._bind[0]
        self._port = int(self._bind[1])
        self._wsgi_app = wsgi_app

    def run(self):
        log.info("Starting Web Server ({t}) on '{h}:{p}'.".format(t=self.__class__.__name__, h=self._host, p=self._port))
        self._run()


# CherryPy WSGI Web Server
import cherrypy.wsgiserver
class CherryPyHttpD(HttpDBase):
    def __init__(self, bind, wsgi_app):
        super(CherryPyHttpD, self).__init__(bind, wsgi_app)
        self._httpd = cherrypy.wsgiserver.CherryPyWSGIServer((self._host, self._port), self._wsgi_app)

    def _run(self):
        self._httpd.start()


# Standard Library Reference WSGI Web Server
import wsgiref.simple_server
class WsgiRefHttpD(HttpDBase):
    def __init__(self, bind, wsgi_app):
        super(WsgiRefHttpD, self).__init__(bind, wsgi_app)
        self._httpd = wsgiref.simple_server.make_server(self._host, self._port, self._wsgi_app)

    def _run(self):
        self._httpd.serve_forever()


# Django development Web Server
import django.core.management
class DjangoHttpD(HttpDBase):
    def __init__(self, bind, wsgi_app):
        super(DjangoHttpD, self).__init__(bind, wsgi_app)

    def _run(self):
        django.core.management.call_command('runserver', self._host + ":" + str(self._port))


# Set web server to be used
HttpD = CherryPyHttpD
#HttpD = WsgiRefHttpD
#HttpD = DjangoHttpD
