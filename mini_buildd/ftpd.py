# coding: utf-8
import os
import stat
import re
import logging

import pyftpdlib.ftpserver

import mini_buildd

log = logging.getLogger(__name__)

# Force pyftpdlib log callbacks to mini_buildd log.
# See http://code.google.com/p/pyftpdlib/wiki/Tutorial#2.1_-_Logging
pyftpdlib.ftpserver.log      = lambda msg: log.info(msg)
pyftpdlib.ftpserver.logline  = lambda msg: log.debug(msg)
pyftpdlib.ftpserver.logerror = lambda msg: log.error(msg)

class FtpDHandler(pyftpdlib.ftpserver.FTPHandler):
    def on_file_received(self, file):
        os.chmod(file, stat.S_IRUSR | stat.S_IRGRP )
        if self._mini_buildd_cfregex.match(file):
            log.info("Queuing incoming changes file: %s" % file);
            self._mini_buildd_queue.put(file)
        else:
            log.debug("Skipping incoming file: %s" % file);


class FtpD(pyftpdlib.ftpserver.FTPServer):
    def __init__(self, bind, home, incoming, repositories, queue):
        self._bind = mini_buildd.misc.BindArgs(bind)

        mini_buildd.misc.mkdirs(os.path.join(home, incoming))
        mini_buildd.misc.mkdirs(os.path.join(home, repositories))

        handler = FtpDHandler
        handler.authorizer = pyftpdlib.ftpserver.DummyAuthorizer()
        handler.authorizer.add_anonymous(homedir=home, perm='')
        handler.authorizer.override_perm(username="anonymous", directory=os.path.join(home, incoming), perm='elrw')
        handler.authorizer.override_perm(username="anonymous", directory=os.path.join(home, repositories), perm='elr', recursive=True)

        handler.banner = "mini-buildd {v} ftp server ready (pyftpdlib {V}).".format(v=mini_buildd.__version__, V=pyftpdlib.ftpserver.__ver__)
        handler._mini_buildd_queue = queue
        handler._mini_buildd_cfregex = re.compile("^.*\.changes$")

        pyftpdlib.ftpserver.FTPServer.__init__(self, self._bind.tuple, handler)

    def run(self):
        self.serve_forever()
