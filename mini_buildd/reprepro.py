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

    def include(self, distribution, changes):
        mini_buildd.misc.call(self._cmd + ["include", distribution, changes])

    def copysrc(self, dest_distribution, source_distribution, package, version):
        return mini_buildd.misc.sose_call(
            self._cmd + ["copysrc", dest_distribution, source_distribution, package, version])

    def removesrc(self, distribution, package, version):
        return mini_buildd.misc.sose_call(
            self._cmd + ["removesrc", distribution, package, version])

    def listmatched(self, distribution, pattern):
        result = []
        for item in mini_buildd.misc.call(self._cmd +
                                          ["--type=dsc",
                                           "--list-format=${$source}|${$codename}|${$sourceversion};",
                                           "listmatched",
                                           distribution,
                                           pattern]).split(";"):
            if item:
                result.append(item.split("|"))
        return result
