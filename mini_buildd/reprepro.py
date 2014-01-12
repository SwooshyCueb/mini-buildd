# -*- coding: utf-8 -*-
"""
Run reprepro commands.
"""
from __future__ import unicode_literals

import os
import shutil
import threading

import logging

import mini_buildd.misc

LOG = logging.getLogger(__name__)

_LOCKS_LOCK = threading.Lock()
_LOCKS = {}


class Reprepro(object):
    """
    Abstraction to reprepro repository commands.

    Locking

    This implicitly provides a locking mechanism to avoid
    parallel calls to the same repository from mini-buildd
    itself. This rules out any failed call due to reprepro
    locking errors in the first place.

    For the case that someone else is using reprepro
    manually, we also always run it with '--waitforlock'.
    """
    def __init__(self, basedir):
        self._basedir = basedir
        self._cmd = ["reprepro", "--verbose", "--waitforlock=10", "--basedir={b}".format(b=basedir)]
        # Seems dict.setdefault 'should' be atomic, but it may be not the case in all versions >=2.6
        # See: http://bugs.python.org/issue13521
        with _LOCKS_LOCK:
            self._lock = _LOCKS.setdefault(self._basedir, threading.Lock())
            LOG.debug("Lock for reprepro repository '{r}': {o}".format(r=self._basedir, o=self._lock))

    def _call(self, args, show_command=False):
        return "{command}{output}".format(command="Running {command}\n".format(command=" ".join(self._cmd + args)) if show_command else "",
                                          output=mini_buildd.misc.sose_call(self._cmd + args))

    def _call_locked(self, args, show_command=False):
        with self._lock:
            return self._call(args, show_command)

    def reindex(self):
        with self._lock:
            # Update reprepro dbs, and delete any packages no longer in dists.
            self._call(["--delete", "clearvanished"])

            # Purge all indices under 'dists/' (clearvanished does not remove indices of vanished distributions)
            shutil.rmtree(os.path.join(self._basedir, "dists"), ignore_errors=True)

            # Finally, rebuild all indices
            self._call(["export"])

    def check(self):
        return self._call_locked(["check"])

    def list(self, pattern, distribution, typ=None, list_max=50):
        result = []
        for item in self._call_locked(["--list-format=${package}|${$type}|${architecture}|${version}|${$source}|${$sourceversion}|${$codename}|${$component};",
                                       "--list-max={m}".format(m=list_max)] +
                                      (["--type={t}".format(t=typ)] if typ else []) +
                                      ["listmatched",
                                       distribution,
                                       pattern]).split(";"):
            if item:
                item_split = item.split("|")
                result.append({"package": item_split[0],
                               "type": item_split[1],
                               "architecture": item_split[2],
                               "version": item_split[3],
                               "source": item_split[4],
                               "sourceversion": item_split[5],
                               "distribution": item_split[6],
                               "component": item_split[7],
                               })
        return result

    def show(self, package):
        result = []
        # reprepro ls format: "${$source} | ${$sourceversion} |    ${$codename} | source\n"
        for item in self._call_locked(["--type=dsc",
                                       "ls",
                                       package]).split("\n"):
            LOG.debug("ls: {i}".format(i=item))
            if item:
                item_split = item.split("|")
                result.append({"source": item_split[0].strip(),
                               "sourceversion": item_split[1].strip(),
                               "distribution": item_split[2].strip(),
                               })
        return result

    def migrate(self, package, src_distribution, dst_distribution, version=None):
        return self._call_locked(["copysrc", dst_distribution, src_distribution, package] + ([version] if version else []), show_command=True)

    def remove(self, package, distribution, version=None):
        return self._call_locked(["removesrc", distribution, package] + ([version] if version else []), show_command=True)

    def install(self, changes, distribution):
        return self._call_locked(["include", distribution, changes], show_command=True)

    def install_dsc(self, dsc, distribution):
        return self._call_locked(["includedsc", distribution, dsc], show_command=True)
