# coding: utf-8
import mini_buildd
import logging

log = logging.getLogger(__name__)

class HttpDBase(object):
    def __init__(self, bind, wsgi_app):
        self._bind = mini_buildd.misc.BindArgs(bind)
        self._wsgi_app = wsgi_app

    def run(self):
        log.info("Starting httpd ({t}) on '{b}'.".format(t=self.__class__.__name__, b=self._bind.string))
        self._run()


# CherryPy WSGI Web Server
import cherrypy.wsgiserver
class CherryPyHttpD(HttpDBase):
    def __init__(self, bind, wsgi_app):
        super(CherryPyHttpD, self).__init__(bind, wsgi_app)
        self._httpd = cherrypy.wsgiserver.CherryPyWSGIServer(self._bind.tuple, self._wsgi_app)

    def _run(self):
        self._httpd.start()


# Standard Library Reference WSGI Web Server
import wsgiref.simple_server
class WsgiRefHttpD(HttpDBase):
    def __init__(self, bind, wsgi_app):
        super(WsgiRefHttpD, self).__init__(bind, wsgi_app)
        self._httpd = wsgiref.simple_server.make_server(self._bind.host, self._bind.port, self._wsgi_app)

    def _run(self):
        self._httpd.serve_forever()


# Django development Web Server
import django.core.management
class DjangoHttpD(HttpDBase):
    def __init__(self, bind, wsgi_app):
        super(DjangoHttpD, self).__init__(bind, wsgi_app)

    def _run(self):
        django.core.management.call_command('runserver', self._bind.string)


# Set web server to be used
HttpD = CherryPyHttpD
#HttpD = WsgiRefHttpD
#HttpD = DjangoHttpD
