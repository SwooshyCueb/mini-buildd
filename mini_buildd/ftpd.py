# coding: utf-8
import os
import stat
import re
import logging

import pyftpdlib.ftpserver

import mini_buildd

log = logging.getLogger(__name__)

# pyftpdlib log callbacks: http://code.google.com/p/pyftpdlib/wiki/Tutorial#2.1_-_Logging
pyftpdlib.ftpserver.log      = lambda msg: log.info(msg)
pyftpdlib.ftpserver.logline  = lambda msg: log.debug(msg)
pyftpdlib.ftpserver.logerror = lambda msg: log.error(msg)

class IncomingFtpHandler(pyftpdlib.ftpserver.FTPHandler):
    def on_file_received(self, file):
        os.chmod(file, stat.S_IRUSR | stat.S_IRGRP )
        if self._mini_buildd_cfregex.match(file):
            log.info("Queuing incoming changes file: %s" % file);
            self._mini_buildd_queue.put(file)
        else:
            log.debug("Skipping incoming file: %s" % file);


class IncomingFtpD(pyftpdlib.ftpserver.FTPServer):
    def __init__(self, bind, path, queue):
        self._bind = mini_buildd.misc.BindArgs(bind)

        mini_buildd.misc.mkdirs(path)

        self._handler = IncomingFtpHandler
        self._handler.authorizer = pyftpdlib.ftpserver.DummyAuthorizer()
        self._handler.authorizer.add_anonymous(homedir=path, perm='elrw')
        self._handler.banner = "mini-buildd {v} ftp server ready (pyftpdlib {V}).".format(v=mini_buildd.__version__, V=pyftpdlib.ftpserver.__ver__)
        self._handler._mini_buildd_queue = queue
        self._handler._mini_buildd_cfregex = re.compile("^.*\.changes$")

        self._server = pyftpdlib.ftpserver.FTPServer(self._bind.tuple, self._handler)

    def run(self):
        self._server.serve_forever()
