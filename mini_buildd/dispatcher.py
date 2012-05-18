# -*- coding: utf-8 -*-
import os
import contextlib
import logging

import mini_buildd

log = logging.getLogger(__name__)

class Dispatcher():
    def __init__(self, incoming_queue, build_queue):
        self._incoming_queue = incoming_queue
        self._build_queue = build_queue

    def run(self):
        while True:
            c = mini_buildd.Changes(self._incoming_queue.get())
            r = c.get_repository()
            if c.is_buildrequest():
                log.info("{p}: Got build request for {r}".format(p=c.get_pkg_id(), r=r.id))
                self._build_queue.put(c)
            elif c.is_buildresult():
                log.info("{p}: Got build result for {r}".format(p=c.get_pkg_id(), r=r.id))
                c.untar(path=r.get_incoming_path())
                r._reprepro.processincoming()
            else:
                log.info("{p}: Got user upload for {r}".format(p=c.get_pkg_id(), r=r.id))
                for br in c.gen_buildrequests():
                    br.upload()

            self._incoming_queue.task_done()
