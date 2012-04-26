# -*- coding: utf-8 -*-
"""
mini-buildd: Command line arguments handling.
"""

import string
import argparse
import logging
import logging.handlers
import os
import sys

import mini_buildd

log = logging.getLogger("mini_buildd")

global _LOG_HANDLERS

def init_logging(args):
    # Add predefinded handlers: console, syslog, file
    _LOG_HANDLERS = {}
    _LOG_HANDLERS["syslog"] = logging.handlers.SysLogHandler(address="/dev/log", facility=logging.handlers.SysLogHandler.LOG_USER)
    _LOG_HANDLERS["console"] = logging.StreamHandler()
    _LOG_HANDLERS["file"] = logging.FileHandler(args.home + "/.mini-buildd.log")

    # Global: Don't propagate exceptions that happen while logging
    logging.raiseExceptions = 0

    for h in string.split(args.loggers + (",console" if args.foreground else ""), ","):
        _LOG_HANDLERS[h].setFormatter(logging.Formatter("mini-buildd(%(name)s): %(levelname)-8s: %(message)s [%(module)s:%(lineno)d]"))
        log.addHandler(_LOG_HANDLERS[h])

    # Finally, set log level
    loglevel=logging.WARNING-(10*(min(2, args.verbosity)-min(2, args.terseness)))
    log.setLevel(loglevel)
