# -*- coding: utf-8 -*-
"""
Run reprepro commands.
"""

import logging

from mini_buildd import misc

log = logging.getLogger(__name__)

class Reprepro():
    def __init__(self, basedir):
        self._cmd = ["reprepro",  "--verbose", "--basedir={b}".format(b=basedir)]

    def clearvanished(self):
        misc.call(self._cmd + ["clearvanished"])

    def export(self):
        misc.call(self._cmd + ["export"])

    def processincoming(self):
        return misc.call(self._cmd + ["processincoming", "INCOMING"])
