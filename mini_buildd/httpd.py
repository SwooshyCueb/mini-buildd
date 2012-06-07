# coding: utf-8
import logging

import cherrypy.wsgiserver

from mini_buildd import misc

log = logging.getLogger(__name__)

def run(bind, wsgi_app):
    " CherryPy WSGI Web Server "
    httpd = cherrypy.wsgiserver.CherryPyWSGIServer(misc.BindArgs(bind).tuple, wsgi_app)
    httpd.start()
