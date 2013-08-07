# -*- coding: utf-8 -*-
"""
Message log: Logs that should also go to the end user.

An instance of MsgLog may replace the standard (python) log;
logs will also go to the django messaging system, and it also
stores the logs so they might used for other (non-django) uses.

Logs done via MsgLog (aka "messages") are intended for the end
user, to be shown in an UI (for us, the django web app or the
command line client).

Log coding idioms to be used::

  # Optional: Alias for MsgLog class in modules where we need it
  from mini_buildd.models.msglog import MsgLog

  # Always: Global standard LOG object, directly after imports)
  LOG = logging.getLogger(__name__)

  # Standard log
  LOG.info("blah blah")

  # Message log
  MsgLog(LOG, request).info("Dear user: blah blah")
"""
from __future__ import unicode_literals

import logging
import inspect

import django.contrib.messages

LOG = logging.getLogger(__name__)


class MsgLog(object):
    def __init__(self, pylog, request):
        self.pylog = pylog
        self.request = request
        self.plain = ""

    @classmethod
    def level2django(cls, level):
        "Map standard python log levels to django's."
        return {logging.DEBUG: django.contrib.messages.DEBUG,
                logging.INFO: django.contrib.messages.INFO,
                logging.WARN: django.contrib.messages.WARNING,
                logging.ERROR: django.contrib.messages.ERROR,
                logging.CRITICAL: django.contrib.messages.ERROR}[level]

    @classmethod
    def _level2prefix(cls, level):
        "Map log levels to prefixes (for text-only output)."
        return {logging.DEBUG: "D",
                logging.INFO: "I",
                logging.WARN: "W",
                logging.ERROR: "E",
                logging.CRITICAL: "C"}[level]

    def log(self, level, msg):
        if self.request:
            django.contrib.messages.add_message(self.request, self.level2django(level), msg)

        # Ouch: Try to get the actual log call's meta flags
        # Ideally, we should be patching the actual line and mod used for standard formatting (seems non-trivial...)
        actual_mod = "n/a"
        actual_line = "n/a"
        try:
            # The actual log call is two frames up
            frame = inspect.stack()[2]
            actual_mod = inspect.getmodulename(frame[1])
            actual_line = frame[2]
        except:
            pass

        self.pylog.log(level, "{m} [{mod}:{l}]".format(m=msg, mod=actual_mod, l=actual_line))
        self.plain += "{p}: {m}\n".format(p=self._level2prefix(level), m=msg)

    def log_text(self, text, level=logging.INFO):
        for msg in text.splitlines():
            self.log(level, msg)

    def debug(self, msg):
        self.log(logging.DEBUG, msg)

    def info(self, msg):
        self.log(logging.INFO, msg)

    def warn(self, msg):
        self.log(logging.WARN, msg)

    def error(self, msg):
        self.log(logging.ERROR, msg)

    def critical(self, msg):
        self.log(logging.CRITICAL, msg)

    def exception(self, msg):
        self.pylog.exception(msg)
