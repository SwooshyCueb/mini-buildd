# coding: utf-8
import logging
import cherrypy
import django
from mini_buildd import misc

log = logging.getLogger(__name__)


def log_init():
    """
    Setup CherryPy to use mini-buildd's logging mechanisms.

    """

    # listener
    def cherry_log(msg, level):
        log.log(level, msg)
        # to enforce 'DEBUG-logging' use the following line instead
        # log.log(logging.DEBUG, msg)

    # subscribe to channel
    cherrypy.engine.subscribe('log', cherry_log)

    # HTTP errors (status codes: 4xx-5xx)
    http_error = cherrypy._cperror.HTTPError
    http_error.set_response = lambda msg: log.log(logging.ERROR, msg)

def run(bind, wsgi_app):
    """
    Run the CherryPy WSGI Web Server.

    :param bind: the bind address to use.
    :type bind: string
    :param wsgi_app: the web application to process.
    :type wsgi_app: WSGI-application

    """

    log_init()

    cherrypy.config.update({'server.socket_host': misc.BindArgs(bind).host,
                            'server.socket_port': misc.BindArgs(bind).port})

    # static files: django admin
    static_base_dir_da = "/usr/share/pyshared/django/contrib/admin"

    if int(django.VERSION[1]) >= 4:
        static_sub_dir_da = "static"
    else:
        static_sub_dir_da = "media"

    static_handler_da = cherrypy.tools.staticdir.handler(section = "/", dir = static_sub_dir_da, root = static_base_dir_da)
    cherrypy.tree.mount(static_handler_da, '/static/admin')

    # static files: mini buildd
    static_base_dir_mb = "/usr/share/pyshared/mini_buildd/static"
    static_sub_dir_mb = "mini_buildd"
    static_handler_mb = cherrypy.tools.staticdir.handler(section = "/", dir = static_sub_dir_mb, root = static_base_dir_mb)
    cherrypy.tree.mount(static_handler_mb,  '/static')

    cherrypy.tree.graft(wsgi_app)
    cherrypy.engine.start()
    cherrypy.engine.block()
