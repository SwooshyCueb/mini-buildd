# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import logging

DEBUG = []

HTTPD_BIND = None

# Global directory paths
HOME_DIR = None

INCOMING_DIR = None
REPOSITORIES_DIR = None

SPOOL_DIR = None
TMP_DIR = None
LOG_DIR = None
LOG_FILE = None
ACCESS_LOG_FILE = None
CHROOTS_DIR = None
CHROOT_LIBDIR = None

MANUAL_DIR = None

# This should never ever be changed
CHAR_ENCODING = "UTF-8"


def log_exception(log, message, exception, level=logging.ERROR):
    msg = "{m}: {e}".format(m=message, e=exception)
    log.log(level, msg)
    if "exception" in DEBUG:
        log.exception(msg)
