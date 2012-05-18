# coding: utf-8
import os
import stat
import re
import logging

import pyftpdlib.ftpserver

import mini_buildd

log = logging.getLogger(__name__)

def log_init():
    """
    Force pyftpdlib log callbacks to the mini_buildd log.

    See http://code.google.com/p/pyftpdlib/wiki/Tutorial#2.1_-_Logging:
     - log: messages intended for the end user.
     - logline: Log commands and responses passing through the command channel.
     - logerror: Log traceback outputs occurring in case of errors.

     As pyftpd "logline" really spews lot of lines, this is only
     enabled in debug mode.
    """
    pyftpdlib.ftpserver.log = lambda msg: log.debug(msg)
    pyftpdlib.ftpserver.logline = lambda msg: log.debug(msg) if mini_buildd.globals.DEBUG else mini_buildd.misc.nop
    pyftpdlib.ftpserver.logerror = lambda msg: log.error(msg)


class FtpDHandler(pyftpdlib.ftpserver.FTPHandler):
    _CHANGES_RE = re.compile("^.*\.changes$")

    def on_file_received(self, f):
        # Make any incoming file read-only as soon as it arrives; avoids multiple user uploads of the same file
        os.chmod(f, stat.S_IRUSR | stat.S_IRGRP)

        if self._CHANGES_RE.match(f):
            log.info("Incoming changes file: {f}".format(f=f))
            self._mini_buildd_queue.put(f)
        else:
            log.debug("Ignoring incoming file: {f}".format(f=f))


class FtpD(pyftpdlib.ftpserver.FTPServer):
    def __init__(self, bind, queue):
        log_init()
        self._bind = mini_buildd.misc.BindArgs(bind)

        handler = FtpDHandler
        handler.authorizer = pyftpdlib.ftpserver.DummyAuthorizer()
        handler.authorizer.add_anonymous(homedir=mini_buildd.globals.HOME_DIR, perm='')
        handler.authorizer.override_perm(username="anonymous", directory=mini_buildd.globals.INCOMING_DIR, perm='elrw')
        handler.authorizer.override_perm(username="anonymous", directory=mini_buildd.globals.REPOSITORIES_DIR, perm='elr', recursive=True)
        handler.authorizer.override_perm(username="anonymous", directory=mini_buildd.globals.LOGS_DIR, perm='elr', recursive=True)

        handler.banner = "mini-buildd {v} ftp server ready (pyftpdlib {V}).".format(v=mini_buildd.__version__, V=pyftpdlib.ftpserver.__ver__)
        handler._mini_buildd_queue = queue

        pyftpdlib.ftpserver.FTPServer.__init__(self, self._bind.tuple, handler)

    def run(self):
        log.info("Starting ftpd on '{b}'.".format(b=self._bind.string))
        self.serve_forever()
