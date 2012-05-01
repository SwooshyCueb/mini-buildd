# -*- coding: utf-8 -*-
import os
import Queue
import logging
import tarfile
import ftplib

import debian.deb822

import mini_buildd

log = logging.getLogger(__name__)

class Changes(debian.deb822.Changes):
    def __init__(self, file_name):
        self._file_name = file_name
        if os.path.exists(file_name):
            super(Changes, self).__init__(file(file_name))
        else:
            super(Changes, self).__init__([])

    def save(self):
        log.info("Save {f}".format(f=self._file_name))
        self.dump(fd=open(self._file_name, "w+"))

class Buildrequest(Changes):
    def __init__(self, file_name, tar_name):
        super(Buildrequest, self).__init__(file_name)
        self._tar_name = tar_name

    def upload(self, host="localhost", port=8067):
        ftp = ftplib.FTP()
        ftp.connect(host, port)
        ftp.login()
        ftp.cwd("/incoming")
        ftp.storbinary("STOR {f}".format(f=os.path.basename(self._file_name)), open(self._file_name))

        try:
            ftp.size(os.path.basename(self._tar_name))
            log.info("Already uploaded to this host: '{f}'...". format(f=self._tar_name))
        except:
            ftp.storbinary("STOR {f}".format(f=os.path.basename(self._tar_name)), open(self._tar_name))


class SourceChanges(Changes):
    def __init__(self, file_name, spool_dir):
        super(SourceChanges, self).__init__(file_name)

        self._spool_dir = os.path.join(spool_dir, os.path.basename(self._file_name))
        log.info("Source changes spool in '{d}'...". format(d=self._spool_dir))

        os.makedirs(self._spool_dir)

        # Build tar file
        self._tar_file = os.path.join(self._spool_dir, os.path.basename(self._file_name)) + ".tar"
        tar = tarfile.open(self._tar_file, "w")
        try:
            tar_add = lambda f: tar.add(f, arcname=os.path.basename(f))
            tar_add(self._file_name)
            for f in self.get_files():
                tar_add(os.path.join(os.path.dirname(self._file_name), f["name"]))
        finally:
            tar.close()

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

    def gen_build_requests(self):
        # Build buildrequest files for all archs
        br_list = []
        for a in self.get_repository().archs.all():
            brf = "{b}_{a}.buildrequest".format(b=self._tar_file, a=a.arch)
            br = Buildrequest(brf, self._tar_file)
            # @todo Add all build information from repository
            br["X-Mini-Buildd-Test"] = "test"
            br.save()
            br_list.append(br)

        return br_list


class Build():
    def __init__(self, f):
        self._f = f

    def run(self):
        log.info("STUB: Building {f}".format(f=self._f))


class Builder():
    def __init__(self, queue):
        self._queue = queue

    def run(self):
        while True:
            f = self._queue.get()
            mini_buildd.misc.start_thread(Build(f))
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
            f = self._incoming_queue.get()
            if os.path.splitext(f)[1] == ".changes":
                # User upload
                c = SourceChanges(f, self._spool_dir)
                for br in c.gen_build_requests():
                    br.upload()

            elif os.path.splitext(f)[1] == ".buildrequest":
                self._build_queue.put(f)
            elif os.path.splitext(f)[1] == ".buildresult":
                log.info("STUB: build result: '{f}'...".format(f=f))
            else:
                raise Exception("Internal error: Wrong incoming file {f}".format(f=f))

            self._incoming_queue.task_done()
