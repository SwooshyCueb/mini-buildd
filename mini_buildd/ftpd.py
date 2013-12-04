# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import stat
import glob
import shutil
import fnmatch
import logging

import debian.deb822

import pyftpdlib.ftpserver

import mini_buildd
import mini_buildd.setup
import mini_buildd.misc

LOG = logging.getLogger(__name__)

# Alas, we need this to be compatible with 0.7 and >= 1.0 versions (see serve_forever below)
# pylint: disable=E1101
try:
    PYFTPDLIB_MAIN_VERSION = pyftpdlib.__ver__.split(".")[0]
except:
    # 0.7 had no __ver__
    PYFTPDLIB_MAIN_VERSION = 0
# pylint: enable=E1101


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


class Incoming(object):
    "Tool collection for some extra incoming directory handling."

    @classmethod
    def is_changes(cls, file_name):
        return fnmatch.fnmatch(file_name, "*.changes")

    @classmethod
    def get_changes(cls):
        return glob.glob(os.path.join(mini_buildd.setup.INCOMING_DIR, "*.changes"))

    @classmethod
    def remove_cruft_files(cls, files):
        """
        Remove all files from list of files not mentioned in a changes file.
        """
        valid_files = []
        for changes_file in files:
            if cls.is_changes(changes_file):
                LOG.debug("Checking: {c}".format(c=changes_file))
                try:
                    for fd in debian.deb822.Changes(mini_buildd.misc.open_utf8(changes_file)).get("Files", []):
                        valid_files.append(fd["name"])
                        LOG.debug("Valid: {c}".format(c=fd["name"]))

                    valid_files.append(os.path.basename(changes_file))
                except Exception as e:
                    mini_buildd.setup.log_exception(LOG, "Invalid changes file: {f}".format(f=changes_file), e, logging.WARNING)

        for f in files:
            if os.path.basename(f) not in valid_files:
                # Be sure to never ever fail, just because cruft removal fails (instead log accordingly)
                try:
                    if os.path.isdir(f):
                        shutil.rmtree(f)
                    else:
                        os.remove(f)
                    LOG.warn("Cruft file (not in any changes file) removed: {f}".format(f=f))
                except Exception as e:
                    mini_buildd.setup.log_exception(LOG, "Can't remove cruft from incoming: {f}".format(f=f), e, logging.CRITICAL)

    @classmethod
    def remove_cruft(cls):
        """
        Remove cruft files from incoming.
        """
        cls.remove_cruft_files(["{p}/{f}".format(p=mini_buildd.setup.INCOMING_DIR, f=f) for f in os.listdir(mini_buildd.setup.INCOMING_DIR)])

    @classmethod
    def requeue_changes(cls, queue):
        """
        Re-queue all existing changes in incoming.

        We must feed the the user uploads first, so the daemon
        does not get any yet-unknown build results (hence the
        sorting).
        """
        for c in sorted(cls.get_changes(), cmp=lambda c0, c1: 1 if fnmatch.fnmatch(c0, "*mini-buildd-build*") else -1):
            LOG.info("Incoming: Re-queuing: {c}".format(c=c))
            queue.put(c)


class FtpDHandler(pyftpdlib.ftpserver.FTPHandler):
    def __init__(self, *args, **kwargs):
        # This does not work with 'super' for some reason
        pyftpdlib.ftpserver.FTPHandler.__init__(self, *args, **kwargs)
        self._mbd_files_received = []

    def on_file_received(self, file_name):
        """
        Make any incoming file read-only as soon as it arrives; avoids overriding uploads of the same file.
        """
        os.chmod(file_name, stat.S_IRUSR | stat.S_IRGRP)
        self._mbd_files_received.append(file_name)
        LOG.info("File received: {f}".format(f=file_name))

    def on_incomplete_file_received(self, file_name):
        LOG.warning("Incomplete file received: {f}".format(f=file_name))
        self._mbd_files_received.append(file_name)

    def on_disconnect(self):
        for file_name in (f for f in self._mbd_files_received if Incoming.is_changes(f)):
            LOG.info("Queuing incoming changes file: {f}".format(f=file_name))
            self.mini_buildd_queue.put(file_name)
        Incoming.remove_cruft_files(self._mbd_files_received)


def run(bind, queue):
    log_init()

    ba = mini_buildd.misc.HoPo(bind)

    handler = FtpDHandler
    handler.authorizer = pyftpdlib.ftpserver.DummyAuthorizer()
    handler.authorizer.add_anonymous(homedir=mini_buildd.setup.HOME_DIR, perm="")
    handler.authorizer.override_perm(username="anonymous", directory=mini_buildd.setup.INCOMING_DIR, perm="elrw")

    handler.banner = "mini-buildd {v} ftp server ready (pyftpdlib {V}).".format(v=mini_buildd.__version__, V=pyftpdlib.ftpserver.__ver__)
    handler.mini_buildd_queue = queue

    Incoming.remove_cruft()
    Incoming.requeue_changes(queue)

    ftpd = pyftpdlib.ftpserver.FTPServer(ba.tuple, handler)
    LOG.info("Starting ftpd on '{b}'.".format(b=ba.string))

    global _RUN
    _RUN = True

# pylint: disable=E1123
    while _RUN:
        if PYFTPDLIB_MAIN_VERSION < 1:
            ftpd.serve_forever(count=1)
        else:
            ftpd.serve_forever(timeout=5.0, blocking=False, handle_exit=False)
# pylint: enable=E1123

    ftpd.close_all()

_RUN = None


def shutdown():
    global _RUN
    _RUN = False
