# coding: utf-8
import os
import stat
import glob
import re
import logging

import pyftpdlib.ftpserver

from mini_buildd import __version__, setup, misc

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
    pyftpdlib.ftpserver.logline = lambda msg: log.debug(msg) if "ftpd" in setup.DEBUG else misc.nop
    pyftpdlib.ftpserver.logerror = lambda msg: log.error(msg)


_CHANGES_RE = re.compile("^.*\.changes$")
def handle_incoming_file(queue, f):
    global _CHANGES_RE
    if _CHANGES_RE.match(f):
        log.info("Incoming changes file: {f}".format(f=f))
        queue.put(f)
    else:
        log.debug("Ignoring incoming file: {f}".format(f=f))

class FtpDHandler(pyftpdlib.ftpserver.FTPHandler):
    def on_file_received(self, f):
        # Make any incoming file read-only as soon as it arrives; avoids multiple user uploads of the same file
        os.chmod(f, stat.S_IRUSR | stat.S_IRGRP)
        handle_incoming_file(self._mini_buildd_queue, f)

def run(bind, queue):
    ".. todo:: ftpd load options"
    log_init()

    ba = misc.BindArgs(bind)

    handler = FtpDHandler
    handler.authorizer = pyftpdlib.ftpserver.DummyAuthorizer()
    handler.authorizer.add_anonymous(homedir=setup.HOME_DIR, perm='')
    handler.authorizer.override_perm(username="anonymous", directory=setup.INCOMING_DIR, perm='elrw')
    handler.authorizer.override_perm(username="anonymous", directory=setup.REPOSITORIES_DIR, perm='elr', recursive=True)
    handler.authorizer.override_perm(username="anonymous", directory=setup.LOG_DIR, perm='elr', recursive=True)

    handler.banner = "mini-buildd {v} ftp server ready (pyftpdlib {V}).".format(v=__version__, V=pyftpdlib.ftpserver.__ver__)
    handler._mini_buildd_queue = queue

    # Re-push all existing files in incoming
    for f in glob.glob(setup.INCOMING_DIR + "/*"):
        handle_incoming_file(queue, f)

    ftpd = pyftpdlib.ftpserver.FTPServer(ba.tuple, handler)
    log.info("Starting ftpd on '{b}'.".format(b=ba.string))

    global _RUN
    _RUN = True
    while _RUN:
        ftpd.serve_forever(count=1)
    ftpd.close()

def shutdown():
    global _RUN
    _RUN = False
