# -*- coding: utf-8 -*-
import logging

import cherrypy
import django

import mini_buildd.misc
import mini_buildd.setup

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
    def add_static_handler(dir, root, path):
        "Shortcut to add a static handler."
        cherrypy.tree.mount(
            cherrypy.tools.staticdir.handler(
                section="/",
                dir=dir,
                root=root,
                content_types={"log": "text/plain", "buildlog": "text/plain"}),
            path)

    log_init()

    cherrypy.config.update({'server.socket_host': mini_buildd.misc.BindArgs(bind).host,
                            'server.socket_port': mini_buildd.misc.BindArgs(bind).port})

    # static files base dir: mini-buildd
    static_base_dir = "/usr/share/pyshared/mini_buildd/static"

    # static files base dir: django admin
    static_base_dir_admin = "/usr/share/pyshared/django/contrib/admin"

    if int(django.VERSION[1]) >= 4:
        static_sub_dir_admin = "static/admin"
    else:
        static_sub_dir_admin = "media"

    add_static_handler(dir=static_sub_dir_admin, root=static_base_dir_admin, path="/static/admin")
    add_static_handler(dir="css", root=static_base_dir, path="/static/css")
    add_static_handler(dir="images", root=static_base_dir, path="/static/images")
    add_static_handler(dir=".", root="/usr/share/doc/mini-buildd/html", path="/manual")
    add_static_handler(dir=".", root=static_base_dir, path="/static")
    add_static_handler(dir=".", root=mini_buildd.setup.LOG_DIR, path="/log")

    # register wsgi app (django)
    cherrypy.tree.graft(wsgi_app)

    cherrypy.engine.start()
    cherrypy.engine.block()
