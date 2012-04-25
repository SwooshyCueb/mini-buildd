# coding: utf-8
import os
import re

import mini_buildd
from pyftpdlib import ftpserver

class FtpHandler(ftpserver.FTPHandler):
    def on_file_received(self, file):
        if self._mini_buildd_cfregex.match(file):
            mini_buildd.log.info("Queuing incoming changes file: %s" % file);
            self._mini_buildd_queue.put(file)
        else:
            mini_buildd.log.debug("Skipping incoming file: %s" % file);

class FtpServer(ftpserver.FTPServer):
    def __init__(self, queue):
        bind = mini_buildd.args.ftpserver_bind.split(":")
        self._host = bind[0]
        self._port = int(bind[1])
        path = os.path.join(mini_buildd.args.home, "incoming")
        mini_buildd.misc.mkdirs(path)

        self._handler = FtpHandler
        self._handler.authorizer = ftpserver.DummyAuthorizer()
        self._handler.authorizer.add_anonymous(homedir=path, perm='elrw')
        self._handler.banner = "mini-buildd {v} ftp server ready (pyftpdlib {V}).".format(v=mini_buildd.__version__, V=ftpserver.__ver__)
        self._handler._mini_buildd_queue = queue
        self._handler._mini_buildd_cfregex = re.compile("^.*\.changes$")

        self._server = ftpserver.FTPServer((self._host, self._port), self._handler)

    def run(self):
        mini_buildd.log.info("Starting Ftp Server on '{h}:{p}'.".format(t=self.__class__.__name__, h=self._host, p=self._port))
        self._server.serve_forever()
