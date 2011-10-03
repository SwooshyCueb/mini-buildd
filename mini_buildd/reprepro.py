# -*- coding: utf-8 -*-
"""
Run reprepro commands.
"""

import os

import mini_buildd

class Reprepro():
    def __init__(self, basedir):
        self._cmd = "reprepro --basedir='{b}' ".format(b=basedir)

    def processincoming(self, cf=""):
        return mini_buildd.misc.run_cmd(self._cmd + "processincoming INCOMING \"{cf}\"".format(cf=os.path.basename(cf)), False)
