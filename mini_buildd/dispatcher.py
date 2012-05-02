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
    def __init__(self, file_path, spool_dir):
        self._file_path = file_path
        self._file_name = os.path.basename(file_path)

        if os.path.exists(file_path):
            super(Changes, self).__init__(file(file_path))
            self._spool_dir = os.path.join(spool_dir, self["Distribution"], "{p}_{v}".format(p=self["Source"], v=self["Version"]))
        else:
            super(Changes, self).__init__([])
            self._spool_dir = None

    def save(self):
        log.info("Save {f}".format(f=self._file_path))
        self.dump(fd=open(self._file_path, "w+"))


class Buildrequest(Changes):
    def __init__(self, file_path, spool_dir):
        super(Buildrequest, self).__init__(file_path, spool_dir)

        # Create spool directory; this may already exist
        if self._spool_dir:
            mini_buildd.misc.mkdirs(self._spool_dir)

        self._tar_path = file_path.rpartition("_")[0]

    def upload(self, host="localhost", port=8067):
        ftp = ftplib.FTP()
        ftp.connect(host, port)
        ftp.login()
        ftp.cwd("/incoming")
        ftp.storbinary("STOR {f}".format(f=self._file_name), open(self._file_path))

        try:
            ftp.size(os.path.basename(self._tar_path))
            log.info("Already uploaded to this host: '{f}'...". format(f=self._tar_path))
        except:
            ftp.storbinary("STOR {f}".format(f=os.path.basename(self._tar_path)), open(self._tar_path))

    def unpack(self):
        path = os.path.join(self._spool_dir, self["Architecture"])
        tar = tarfile.open(self._tar_path, "r")
        tar.extractall(path=path)
        tar.close()
        return path

class SourceChanges(Changes):
    def __init__(self, file_path, spool_dir):
        super(SourceChanges, self).__init__(file_path, spool_dir)
        self._base_spool_dir = spool_dir

        # Create spool directory; this must not yet exist for a SourceChanges file.
        os.makedirs(self._spool_dir)

        self._tar_path = os.path.join(self._spool_dir, self._file_name) + ".tar"
        tar = tarfile.open(self._tar_path, "w")
        try:
            tar_add = lambda f: tar.add(f, arcname=os.path.basename(f))
            tar_add(self._file_path)
            for f in self.get_files():
                tar_add(os.path.join(os.path.dirname(self._file_path), f["name"]))
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
            brf = "{b}_{a}.buildrequest".format(b=self._tar_path, a=a.arch)
            br = Buildrequest(brf, self._base_spool_dir)
            # @todo Add all build information from repository
            for v in ["Distribution", "Source", "Version"]:
                br[v] = self[v]
            br["Architecture"] = a.arch
            br.save()
            br_list.append(br)

        return br_list


class Build():
    def __init__(self, spool_dir, f):
        self._f = f
        self._spool_dir = spool_dir

    def run(self):
        br = Buildrequest(self._f, self._spool_dir)
        path = br.unpack()
        log.info("STUB: Building: {p}".format(p=path))


class Builder():
    def __init__(self, spool_dir, queue):
        self._queue = queue
        self._spool_dir = spool_dir

    def run(self):
        while True:
            f = self._queue.get()
            mini_buildd.misc.start_thread(Build(self._spool_dir, f))
            self._queue.task_done()


class Dispatcher():
    def __init__(self, spool_dir, queue):
        self._incoming_queue = queue
        self._spool_dir = spool_dir

        # Queue of all local builds
        self._build_queue = Queue.Queue(maxsize=0)
        self._builder = Builder(self._spool_dir, self._build_queue)

    def run(self):
        mini_buildd.misc.start_thread(self._builder)
        while True:
            f = self._incoming_queue.get()
            ext = os.path.splitext(f)[1]
            if ext == ".changes":
                # User upload
                c = SourceChanges(f, self._spool_dir)
                for br in c.gen_build_requests():
                    br.upload()

            elif ext == ".buildrequest":
                self._build_queue.put(f)
            elif ext == ".buildresult":
                log.info("STUB: build result: '{f}'...".format(f=f))
            else:
                raise Exception("Internal error: Wrong incoming file {f}".format(f=f))

            self._incoming_queue.task_done()
