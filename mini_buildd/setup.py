# -*- coding: utf-8 -*-
from __future__ import unicode_literals

DEBUG = []

HTTPD_BIND = None

# Global directory paths
HOME_DIR = None

INCOMING_DIR = None
REPOSITORIES_DIR = None

SPOOL_DIR = None
LOG_DIR = None
CHROOTS_DIR = None
CHROOT_LIBDIR = None

MANUAL_DIR = None


def log_exception(log, message, exception):
    msg = "{m}: {e}".format(m=message, e=exception)
    if "exception" in DEBUG:
        log.exception(msg)
    else:
        log.error(msg)
