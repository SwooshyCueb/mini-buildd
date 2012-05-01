# -*- coding: utf-8 -*-
import os
import Queue
import logging
import tarfile

import debian.deb822

import mini_buildd

log = logging.getLogger(__name__)

class Changes(debian.deb822.Changes):
    def __init__(self, file_name):
        self._file_name = file_name
        if not os.path.exists(file_name):
            open(file_name, 'w').close()
        super(Changes, self).__init__(file(file_name))

    def get_files(self):
        try:
            return self["Files"]
        except:
            return {}

    def get_repository(self):
        from mini_buildd.models import Repository
        dist = self["Distribution"]
        r_id = dist.split("-")[1]
        log.debug(dist + "/" + r_id)

        r = Repository.objects.get(id=r_id)
        # @todo Check that base dist is really supported by this repo
        return r

    def save(self):
        log.info("Save {f}".format(f=self._file_name))
        self.dump(fd=open(self._file_name, "w+"))

    def gen_build_requests(self, spool_dir):
        d = os.path.join(spool_dir, os.path.basename(self._file_name))
        log.info("Generating build requests in '{d}'...". format(d=d))

        os.makedirs(d)
        # Build tar file
        try:
            tar_file = os.path.join(d, os.path.basename(self._file_name)) + ".tar"
            tar = tarfile.open(tar_file, "w")
            tar_add = lambda f: tar.add(f, arcname=os.path.basename(f))
            tar_add(self._file_name)
            for f in self.get_files():
                tar_add(os.path.join(os.path.dirname(self._file_name), f["name"]))
        finally:
            tar.close()

        # Build buildrequest files for all archs
        for a in self.get_repository().archs.all():
            brf = "{b}_{a}.buildrequest".format(b=tar_file, a=a.arch)
            br = Changes(brf)
            br["X-Mini-Buildd-Test"] = "popest"
            br.save()


class Builder():
    def __init__(self, queue):
        self._queue = queue
    def run(self):
        while True:
            f = self._queue.get()
            log.info("Builder got: {d}".format(d=f))
            self._queue.task_done()


class Dispatcher():
    def __init__(self, spool_dir, queue):
        self._incoming_queue = queue
        self._spool_dir = spool_dir

        # Queue of all local builds
        self._build_queue = Queue.Queue(maxsize=0)
        self._builder = Builder(self._build_queue)

    def run(self):
        mini_buildd.misc.start_thread(self._builder)
        while True:
            c = Changes(self._incoming_queue.get())
            if c["Architecture"] == "source":
                c.gen_build_requests(self._spool_dir)
            else:
                log.info("Got C for {d}: {s}-{v}:{a}".format(d=c["Distribution"], s=c["Source"], v=c["Version"], a=c["Architecture"]))

            self._incoming_queue.task_done()
