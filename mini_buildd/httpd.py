# coding: utf-8
import logging
import cherrypy
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

    static_base_dir = "/usr/share/pyshared/mini_buildd/static"
    static_handler = cherrypy.tools.staticdir.handler(section = "/", dir = "mini_buildd", root = static_base_dir)
    cherrypy.tree.mount(static_handler, '/static')

    cherrypy.tree.graft(wsgi_app)
    cherrypy.engine.start()
    cherrypy.engine.block()
