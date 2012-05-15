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
    def on_file_received(self, f):
        # Make any incoming file read-only as soon as it arrives; avoids multiple user uploads of the same file
        os.chmod(f, stat.S_IRUSR | stat.S_IRGRP)

        if self._mini_buildd_queue_regex.match(f):
            log.info("Queuing incoming file: {f}".format(f=f))
            self._mini_buildd_queue.put(f)
        else:
            log.debug("Non-queue-able incoming file: {f}".format(f=f))


class FtpD(pyftpdlib.ftpserver.FTPServer):
    def __init__(self, bind, home, incoming, repositories, queue, queue_regex):
        log_init()
        self._bind = mini_buildd.misc.BindArgs(bind)

        # @todo Arguably not the right place to create these dirs
        mini_buildd.misc.mkdirs(os.path.join(home, incoming))
        mini_buildd.misc.mkdirs(os.path.join(home, repositories))

        handler = FtpDHandler
        handler.authorizer = pyftpdlib.ftpserver.DummyAuthorizer()
        handler.authorizer.add_anonymous(homedir=home, perm='')
        handler.authorizer.override_perm(username="anonymous", directory=os.path.join(home, incoming), perm='elrw')
        handler.authorizer.override_perm(username="anonymous", directory=os.path.join(home, repositories), perm='elr', recursive=True)

        handler.banner = "mini-buildd {v} ftp server ready (pyftpdlib {V}).".format(v=mini_buildd.__version__, V=pyftpdlib.ftpserver.__ver__)
        handler._mini_buildd_queue = queue
        handler._mini_buildd_queue_regex = re.compile(queue_regex)

        pyftpdlib.ftpserver.FTPServer.__init__(self, self._bind.tuple, handler)

    def run(self):
        log.info("Starting ftpd on '{b}'.".format(b=self._bind.string))
        self.serve_forever()
