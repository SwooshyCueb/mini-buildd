# -*- coding: utf-8 -*-
import logging

import cherrypy

import mini_buildd.misc
import mini_buildd.setup

LOG = logging.getLogger(__name__)


def log_init():
    """
    Setup CherryPy to use mini-buildd's logging mechanisms.
    """

    # listener
    def cherry_log(msg, level):
        LOG.log(level, msg)

    # subscribe to channel
    cherrypy.engine.subscribe('log', cherry_log)

    # turn off stderr/stdout logging
    cherrypy.log.screen = False

    # HTTP errors (status codes: 4xx-5xx)
    cherrypy.HTTPError.set_response = lambda msg: LOG.log(logging.ERROR, msg)


def shutdown():
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
    def add_static_handler(directory, root, path):
        "Shortcut to add a static handler."
        cherrypy.tree.mount(
            cherrypy.tools.staticdir.handler(
                section="/",
                dir=directory,
                root=root,
                content_types={"log": "text/plain", "buildlog": "text/plain"}),
            path)

    log_init()

    cherrypy.config.update({'server.socket_host': mini_buildd.misc.HoPo(bind).host,
                            'server.socket_port': mini_buildd.misc.HoPo(bind).port})

    # Django: Add our own static directory
    add_static_handler(directory=".",
                       root="/usr/share/pyshared/mini_buildd/static",
                       path="/static")

    # Django: Add static support for the admin app
    add_static_handler(directory="static/admin",
                       root="/usr/share/pyshared/django/contrib/admin",
                       path="/static/admin")

    # Serve our Debian-installed html manual directly
    add_static_handler(directory=".", root="/usr/share/doc/mini-buildd/html", path="/manual")

    # Serve repositories and log directories
    add_static_handler(directory=".", root=mini_buildd.setup.REPOSITORIES_DIR, path="/repositories")
    add_static_handler(directory=".", root=mini_buildd.setup.LOG_DIR, path="/log")

    # register wsgi app (django)
    cherrypy.tree.graft(wsgi_app)

    cherrypy.engine.start()
    cherrypy.engine.block()
