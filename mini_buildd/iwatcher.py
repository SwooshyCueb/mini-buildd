# -*- coding: utf-8 -*-
"""
Watch incoming and deliver new changes files to a queue.
"""

import re
import os
import pyinotify

import mini_buildd

class IWatcher():
    class Handler(pyinotify.ProcessEvent):
        def my_init(self, queue):
            self._queue = queue
            self._cfregex = re.compile("^.*\.changes$")

        def processFile(self, pathname):
            if self._cfregex.match(pathname):
                mini_buildd.log.info("Queuing file: %s" % pathname);
                self._queue.put(pathname)
            else:
                mini_buildd.log.debug("Skipping file: %s" % pathname);

        def processEvent(self, event):
            mini_buildd.log.debug("IN_CREATE event in incoming: %s" % str(event))
            self.processFile(event.pathname)

        def process_IN_CREATE(self, event):
            self.processEvent(event)

        def process_IN_MOVED_TO(self, event):
            self.processEvent(event)

    def __init__(self, queue, repository):
        self._idir = repository.get_incoming_path()
        self._handler = self.Handler(queue=queue)
        self._wm = pyinotify.WatchManager()
        self._notifier = pyinotify.Notifier(self._wm, default_proc_fun=self._handler)
        self._wm.add_watch(self._idir, pyinotify.IN_CREATE | pyinotify.IN_MOVED_TO)
        mini_buildd.log.info("Watcher created for: {r} (watching: {i})".format(r=str(repository), i=self._idir))

    def run(self):
        # Scan existing files once
        for f in os.listdir(self._idir):
            self._handler.processFile(os.path.join(self._idir, f))
        # Now, just watch for changes
        self._notifier.loop(daemonize=False)
