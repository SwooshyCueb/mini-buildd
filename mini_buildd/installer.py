# -*- coding: utf-8 -*-
import os
import logging

from debian import deb822

import mini_buildd

log = logging.getLogger(__name__)

class Installer():
    def __init__(self, queue):
        self._queue = queue

        # Temporary: Try to find preinstall script as long as it's not converted to python
        self._preinstall = "No preinstall script found!!"
        for p in ("./lib/mbd-preinstall", "/usr/share/mini-buildd/mbd-preinstall"):
            if os.path.exists(p):
                self._preinstall = p
                break

        log.info("Installer: Using preinstalls script %s" % self._preinstall)

    def get_repository_from_dist(self, dist):
        from mini_buildd.models import Repository
        r_id = dist.split("-")[1]
        log.debug(dist + "/" + r_id)

        r = Repository.objects.get(id=r_id)
        # @todo Check that base dist is really supported by this repo
        return r

    def install(self, cf):
        d = deb822.Changes(file(cf))
        log.info("CF for {d}: {s}-{v}:{a}".format(d=d["Distribution"], s=d["Source"], v=d["Version"], a=d["Architecture"]))
        r = self.get_repository_from_dist(d["Distribution"])
        mini_buildd.misc.run_cmd(self._preinstall + " " + cf)
        return r.processincoming(cf=cf)

    def run(self):
        while True:
            item = self._queue.get()
            self.install(item)
            self._queue.task_done()
