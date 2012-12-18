# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import stat
import glob
import fnmatch
import re
import logging

import pyftpdlib.ftpserver

import mini_buildd
import mini_buildd.setup
import mini_buildd.misc

LOG = logging.getLogger(__name__)


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
    pyftpdlib.ftpserver.log = LOG.info
    pyftpdlib.ftpserver.logline = LOG.debug
    pyftpdlib.ftpserver.logerror = LOG.error


_CHANGES_RE = re.compile(r"^.*\.changes$")


def handle_incoming_file(queue, file_name):
    if _CHANGES_RE.match(file_name):
        LOG.info("Incoming changes file: {f}".format(f=file_name))
        queue.put(file_name)
    else:
        LOG.debug("Ignoring incoming file: {f}".format(f=file_name))


class FtpDHandler(pyftpdlib.ftpserver.FTPHandler):
    def on_file_received(self, file_name):
        """
        Make any incoming file read-only as soon as it arrives; avoids overriding uploads of the same file.
        """
        os.chmod(file_name, stat.S_IRUSR | stat.S_IRGRP)
        handle_incoming_file(self.mini_buildd_queue, file_name)


def run(bind, queue):
    log_init()

    ba = mini_buildd.misc.HoPo(bind)

    handler = FtpDHandler
    handler.authorizer = pyftpdlib.ftpserver.DummyAuthorizer()
    handler.authorizer.add_anonymous(homedir=mini_buildd.setup.HOME_DIR, perm='')
    handler.authorizer.override_perm(username="anonymous", directory=mini_buildd.setup.INCOMING_DIR, perm='elrw')

    handler.banner = "mini-buildd {v} ftp server ready (pyftpdlib {V}).".format(v=mini_buildd.__version__, V=pyftpdlib.ftpserver.__ver__)
    handler.mini_buildd_queue = queue

    # Re-feed all existing changes in incoming
    # We must feed the the user uploads first, so the daemon does not get any yet-unknown build results
    changes = glob.glob(mini_buildd.setup.INCOMING_DIR + "/*.changes")
    for f in [c for c in changes if not fnmatch.fnmatch(c, "*mini-buildd-build*")]:
        queue.put(f)
    for f in [c for c in changes if fnmatch.fnmatch(c, "*mini-buildd-build*")]:
        queue.put(f)

    ftpd = pyftpdlib.ftpserver.FTPServer(ba.tuple, handler)
    LOG.info("Starting ftpd on '{b}'.".format(b=ba.string))

    global _RUN
    _RUN = True
    while _RUN:
        ftpd.serve_forever(count=1)
    ftpd.close()

_RUN = None


def shutdown():
    global _RUN
    _RUN = False
