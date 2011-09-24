# coding: utf-8
import string

import wsgiref.simple_server

import mini_buildd

class WebServer():
    def __init__(self, django):
        mini_buildd.log.info("Starting wsgi web server: '{b}'.".format(b=mini_buildd.opts.bind))
        bind = string.split(mini_buildd.opts.bind, ":")
        self._httpd = wsgiref.simple_server.make_server(bind[0], int(bind[1]), django)

    def run(self):
        self._httpd.serve_forever()
