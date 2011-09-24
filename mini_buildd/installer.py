# -*- coding: utf-8 -*-
import os

import mini_buildd

class Installer():
    def __init__(self, queue, no_act):
        self._queue = queue
        self._no_act = no_act

        # Temporary: Try to find preinstall script as long as it's not converted to python
        self._preinstall = "No preinstall script found!!"
        for p in ("./lib/mbd-preinstall", "/usr/share/mini-buildd/mbd-preinstall"):
            if os.path.exists(p):
                self._preinstall = p
                break

        mini_buildd.log.info("Installer: Using preinstalls script %s" % self._preinstall)

    def install(self, cf):
        if mini_buildd.misc.run_cmd(self._preinstall + " " + cf, self._no_act):
            return mini_buildd.misc.run_cmd("reprepro --basedir=/home/mini-buildd/rep processincoming INCOMING " + os.path.basename(cf), self._no_act)

    def run(self):
        while True:
            item = self._queue.get()
            self.install(item)
            self._queue.task_done()
