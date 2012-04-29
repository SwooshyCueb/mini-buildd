# -*- coding: utf-8 -*-
import os
import Queue
import logging
import sys

import debian.deb822

import mini_buildd

log = logging.getLogger(__name__)

class Builder():
    def __init__(self, queue):
        self._queue = queue

    def run(self):
        while True:
            f = self._queue.get()
            log.info("Builder got: {d}".format(d=f))
            self._queue.task_done()

class Dispatcher():
    def __init__(self, queue):
        self._incoming_queue = queue

        # Queue of all local builds
        self._build_queue = Queue.Queue(maxsize=0)
        self._builder = Builder(self._build_queue)

    def get_repository_from_dist(self, dist):
        from mini_buildd.models import Repository
        r_id = dist.split("-")[1]
        log.debug(dist + "/" + r_id)

        r = Repository.objects.get(id=r_id)
        # @todo Check that base dist is really supported by this repo
        return r

    def run(self):
        mini_buildd.misc.start_thread(self._builder)
        while True:
            cf = self._incoming_queue.get()
            c = debian.deb822.Changes(file(cf))

            if c["Architecture"] == "source":
                log.info("New SOURCE {d}: {s}-{v}:{a}".format(d=c["Distribution"], s=c["Source"], v=c["Version"], a=c["Architecture"]))
                r = self.get_repository_from_dist(c["Distribution"])
                for a in r.archs.all():
                    log.info("Generate build request for {a}".format(a=a))
                    # @todo generate arch-request changes, and upload them
            else:
                log.info("Got C for {d}: {s}-{v}:{a}".format(d=c["Distribution"], s=c["Source"], v=c["Version"], a=c["Architecture"]))

            self._incoming_queue.task_done()
