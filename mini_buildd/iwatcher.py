# coding: utf-8

"""
Watch incoming and deliver new changes files to a queue.
"""

import re
import pyinotify

from mini_buildd.log import log

class IWatcher():
    class Handler(pyinotify.ProcessEvent):
        def my_init(self, queue):
            self._queue = queue
            self._cfregex = re.compile("^.*\.changes$")

        def process_IN_CREATE(self, event):
            log.debug("IN_CREATE event in incoming: %s" % str(event))
            if self._cfregex.match(event.pathname):
                self._queue.put(event.pathname)

    def __init__(self, queue, idir):
        log.info("Watching incoming: %s" % idir)
        self._handler = self.Handler(queue=queue)
        self._wm = pyinotify.WatchManager()
        self._notifier = pyinotify.Notifier(self._wm, default_proc_fun=self._handler)
        self._wm.add_watch(idir, pyinotify.IN_CREATE)

    def run(self):
        self._notifier.loop(daemonize=False)
