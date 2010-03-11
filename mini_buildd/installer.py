# coding: utf-8

import os

from mini_buildd.log import log
import mini_buildd.misc

class Installer():
    def __init__(self, queue, no_act):
        self._queue = queue
        self._no_act = no_act

        for p in ('./lib/mbd-preinstall', '/usr/share/mini-buildd/mbd-preinstall'):
            if os.path.exists(p):
                self._preinstall = p
                break

        log.info("Installer: Using preinstalls script %s" % self._preinstall)

    def install(self, cf):
        if mini_buildd.misc.run_cmd(self._preinstall + " " + cf, self._no_act):
            return mini_buildd.misc.run_cmd("reprepro --basedir=/home/mini-buildd/rep processincoming INCOMING " + os.path.basename(cf), self._no_act)

    def run(self):
        while True:
            item = self._queue.get()
            self.install(item)
            self._queue.task_done()
