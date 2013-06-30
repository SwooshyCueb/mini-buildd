# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import sys
import logging

import cherrypy

import mini_buildd.misc
import mini_buildd.setup

LOG = logging.getLogger(__name__)


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
        mime_text_plain = "text/plain; charset={charset}".format(charset=mini_buildd.setup.CHAR_ENCODING)

        cherrypy.tree.mount(
            cherrypy.tools.staticdir.handler(
                section="/",
                dir=directory,
                root=root,
                content_types={"log": mime_text_plain,
                               "buildlog": mime_text_plain,
                               "changes": mime_text_plain,
                               "dsc": mime_text_plain}),
            path)

    cherrypy.config.update({"server.socket_host": mini_buildd.misc.HoPo(bind).host,
                            "server.socket_port": mini_buildd.misc.HoPo(bind).port,
                            "engine.autoreload_on": False,
                            "checker.on": False,
                            "tools.log_headers.on": False,
                            "request.show_tracebacks": False,
                            "request.show_mismatched_params": False,
                            "log.error_file": None,
                            "log.access_file": None,
                            "log.screen": False})

    # Redirect cherrypy's error log to mini-buildd's logging
    cherrypy.engine.subscribe("log", lambda msg, level: LOG.log(level, "CHERRYPY: {m}".format(m=msg)))

    # Set up a rotating file handler for cherrypy's access log
    handler = logging.handlers.RotatingFileHandler(
        mini_buildd.setup.ACCESS_LOG_FILE,
        maxBytes=5000000,
        backupCount=9,
        encoding="UTF-8")
    handler.setLevel(logging.DEBUG)
# pylint: disable=W0212
    handler.setFormatter(cherrypy._cplogging.logfmt)
# pylint: enable=W0212
    cherrypy.log.access_log.addHandler(handler)

    # Django: Add our own static directory
    add_static_handler(directory=".",
                       root="/usr/share/pyshared/mini_buildd/static",
                       path="/static")

    # Django: Add static support for the admin app
    add_static_handler(directory="static/admin",
                       root="/usr/lib/python{major}.{minor}/dist-packages/django/contrib/admin".format(major=sys.version_info[0], minor=sys.version_info[1]),
                       path="/static/admin")

    # Serve our Debian-installed html documentation directly
    add_static_handler(directory=".", root="/usr/share/doc/mini-buildd/html", path="/doc")

    # Serve repositories and log directories
    add_static_handler(directory=".", root=mini_buildd.setup.REPOSITORIES_DIR, path="/repositories")
    add_static_handler(directory=".", root=mini_buildd.setup.LOG_DIR, path="/log")

    # register wsgi app (django)
    cherrypy.tree.graft(wsgi_app)

    cherrypy.engine.start()
    cherrypy.engine.block()
