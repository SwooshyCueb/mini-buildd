# -*- coding: utf-8 -*-
"""
Run reprepro commands.
"""
from __future__ import unicode_literals

import os
import shutil

import logging

import mini_buildd.misc

LOG = logging.getLogger(__name__)


class Reprepro():
    def __init__(self, basedir):
        self._basedir = basedir
        self._cmd = ["reprepro", "--verbose", "--basedir={b}".format(b=basedir)]

    def reindex(self):
        # Update reprepro dbs, and delete any packages no longer in dists.
        mini_buildd.misc.call(self._cmd + ["--delete", "clearvanished"])

        # Purge all indices under 'dists/' (clearvanished does not remove indices of vanished distributions)
        shutil.rmtree(os.path.join(self._basedir, "dists"), ignore_errors=True)

        # Finally, rebuild all indices
        mini_buildd.misc.call(self._cmd + ["export"])

    def check(self):
        mini_buildd.misc.call(self._cmd + ["check"])

    def list(self, pattern, distribution, typ=None, list_max=50):
        result = []
        for item in mini_buildd.misc.call(self._cmd +
                                          ["--list-format=${package}|${$type}|${architecture}|${version}|${$source}|${$sourceversion}|${$codename}|${$component};",
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
        for item in mini_buildd.misc.call(self._cmd +
                                          ["--type=dsc",
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
        return mini_buildd.misc.sose_call(self._cmd + ["copysrc", dst_distribution, src_distribution, package] + ([version] if version else []))

    def remove(self, package, distribution, version=None):
        return mini_buildd.misc.sose_call(self._cmd + ["removesrc", distribution, package] + ([version] if version else []))

    def install(self, changes, distribution):
        return mini_buildd.misc.sose_call(self._cmd + ["include", distribution, changes])
