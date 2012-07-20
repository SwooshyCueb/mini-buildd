# -*- coding: utf-8 -*-
"""
Run reprepro commands.
"""

import logging

import mini_buildd.misc

log = logging.getLogger(__name__)


class Reprepro():
    def __init__(self, basedir):
        self._cmd = ["reprepro", "--verbose", "--basedir={b}".format(b=basedir)]

    def clearvanished(self):
        mini_buildd.misc.call(self._cmd + ["clearvanished"])

    def export(self):
        mini_buildd.misc.call(self._cmd + ["export"])

    def processincoming(self):
        return mini_buildd.misc.call(self._cmd + ["processincoming", "INCOMING"])

    def listmatched(self, pattern, dist):
        return mini_buildd.misc.call(
            self._cmd +
            ["--type=dsc",
             "--list-format=${$source}|${$sourceversion}|${$codename};",
             "listmatched",
             dist,
             pattern])

    def copysrc(self, dest_distribution, source_distribution, package, version):
        return mini_buildd.misc.call(
            self._cmd + ["copysrc", dest_distribution, source_distribution, package, version])
