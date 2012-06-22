# coding: utf-8
import logging
import cherrypy
import django
from mini_buildd import misc, setup

log = logging.getLogger(__name__)

def log_init():
    """
    Setup CherryPy to use mini-buildd's logging mechanisms.

    """

    # listener
    def cherry_log(msg, level):
        log.log(level, msg)

    # subscribe to channel
    cherrypy.engine.subscribe('log', cherry_log)

    # turn off stderr/stdout logging
    cherrypy.log.screen = False

    # HTTP errors (status codes: 4xx-5xx)
    http_error = cherrypy._cperror.HTTPError
    http_error.set_response = lambda msg: log.log(logging.ERROR, msg)

def exit():
    """
    Stop the CherryPy engine.
    """
    cherrypy.engine.exit()

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

    # static files base dir: mini-buildd
    static_base_dir = "/usr/share/pyshared/mini_buildd/static"

    # static files base dir: manual
    static_base_dir_manual = "/usr/share/doc/mini-buildd/html"

    # static files base dir: django admin
    static_base_dir_admin = "/usr/share/pyshared/django/contrib/admin"

    if int(django.VERSION[1]) >= 4:
        static_sub_dir_admin = "static"
    else:
        static_sub_dir_admin = "media"

    static_handler_admin = cherrypy.tools.staticdir.handler(section = "/", dir = static_sub_dir_admin, root = static_base_dir_admin)
    cherrypy.tree.mount(static_handler_admin, '/static/admin')

    # static files: css
    static_sub_dir_css = "css"
    static_handler_css = cherrypy.tools.staticdir.handler(section = "/", dir = static_sub_dir_css, root = static_base_dir)
    cherrypy.tree.mount(static_handler_css, '/static/css')

    # static files: images
    static_sub_dir_images = "images"
    static_handler_images = cherrypy.tools.staticdir.handler(section = "/", dir = static_sub_dir_images, root = static_base_dir)
    cherrypy.tree.mount(static_handler_images, '/static/images')

    # static files: manual
    static_handler_manual = cherrypy.tools.staticdir.handler(section = "/", dir = ".", root = static_base_dir_manual)
    cherrypy.tree.mount(static_handler_manual, '/manual')

    # static files: .
    static_handler = cherrypy.tools.staticdir.handler(section = "/", dir = ".", root = static_base_dir)
    cherrypy.tree.mount(static_handler, '/static')

    # access mini-buildd's log dir
    static_handler_log = cherrypy.tools.staticdir.handler(section = "/", dir = ".", root = setup.LOG_DIR)
    cherrypy.tree.mount(static_handler_log, '/log')

    # register wsgi app (django)
    cherrypy.tree.graft(wsgi_app)

    cherrypy.engine.start()
    cherrypy.engine.block()
