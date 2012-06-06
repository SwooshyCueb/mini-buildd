# -*- coding: utf-8 -*-
import os, logging, tarfile, ftplib, re, contextlib

import debian.deb822

from mini_buildd import setup, misc

log = logging.getLogger(__name__)

class Changes(debian.deb822.Changes):
    BUILDREQUEST_RE = re.compile("^.+_mini-buildd-buildrequest_[^_]+.changes$")
    BUILDRESULT_RE = re.compile("^.+_mini-buildd-buildresult_[^_]+.changes$")

    def __init__(self, file_path):
        self._file_path = file_path
        self._file_name = os.path.basename(file_path)
        super(Changes, self).__init__(file(file_path) if os.path.exists(file_path) else [])
        # Be sure base dir is always available
        misc.mkdirs(os.path.dirname(file_path))

    def is_buildrequest(self):
        return self.BUILDREQUEST_RE.match(self._file_name)

    def is_buildresult(self):
        return self.BUILDRESULT_RE.match(self._file_name)

    def get_repository(self):
        ".. todo:: Check that base dist is really supported by this repo"
        from models import Repository
        dist = self["Distribution"]
        r_id = dist.split("-")[1]
        # using unicode leads to strange logging behavior => use str() or encode("utf-8") as workaround
        log.debug(str(dist + "/" + r_id))

        r = Repository.objects.get(id=r_id)
        return r

    def get_spool_dir(self, base_dir):
        return os.path.join(base_dir, self["Distribution"], self["Source"], self["Version"], self["Architecture"])

    def get_pkg_id(self):
        return "{s}_{v}".format(s=self["Source"], v=self["Version"])

    def get_files(self):
        return self["Files"] if "Files" in self else []

    def add_file(self, fn):
        if not "Files" in self:
            self["Files"] = []
        self["Files"].append({"md5sum": misc.md5_of_file(fn),
                              "size": os.path.getsize(fn),
                              "section": "mini-buildd",
                              "priority": "extra",
                              "name": os.path.basename(fn)})

    def save(self):
        log.info("Saving changes: {f}".format(f=self._file_path))
        self.dump(fd=open(self._file_path, "w+"))

    def upload(self, host="localhost", port=8067):
        log.info("FTP: Uploading changes: '{f}' to '{h}'...". format(f=self._file_name, h=host))
        ftp = ftplib.FTP()
        ftp.connect(host, port)
        ftp.login()
        ftp.cwd("/incoming")
        for fd in self.get_files() + [ {"name": self._file_name} ]:
            f = fd["name"]
            log.debug("FTP: Uploading file: '{f}'". format(f=f))
            ftp.storbinary("STOR {f}".format(f=f), open(os.path.join(os.path.dirname(self._file_path), f)))

    def tar(self, tar_path, add_files=[]):
        with contextlib.closing(tarfile.open(tar_path, "w")) as tar:
            tar_add = lambda f: tar.add(f, arcname=os.path.basename(f))
            tar_add(self._file_path)
            for f in self.get_files():
                tar_add(os.path.join(os.path.dirname(self._file_path), f["name"]))
            for f in add_files:
                tar_add(f)

    def untar(self, path):
        tar_file = self._file_path + ".tar"
        if os.path.exists(tar_file):
            with contextlib.closing(tarfile.open(tar_file, "r")) as tar:
                tar.extractall(path=path)
        else:
            log.info("No tar file (skipping): {f}".format(f=tar_file))

    def gen_buildrequests(self):
        # Build buildrequest files for all archs
        br_list = []
        r = self.get_repository()
        for a in r.archs.all():
            path = os.path.join(setup.SPOOL_DIR, self["Distribution"], self["Source"], self["Version"], a.arch)
            br = Changes(os.path.join(path, "{b}_mini-buildd-buildrequest_{a}.changes".format(b=self.get_pkg_id(), a=a.arch)))
            for v in ["Distribution", "Source", "Version"]:
                br[v] = self[v]

            codename = br["Distribution"].split("-")[0]

            # Generate sources.list to be used
            open(os.path.join(path, "apt_sources.list"), 'w').write(r.get_apt_sources_list(self["Distribution"]))
            open(os.path.join(path, "apt_preferences"), 'w').write(r.get_apt_preferences())

            # Generate tar from original changes
            self.tar(tar_path=br._file_path + ".tar", add_files=[os.path.join(path, "apt_sources.list"), os.path.join(path, "apt_preferences")])
            br.add_file(br._file_path + ".tar")

            br["Base-Distribution"] = codename
            br["Architecture"] = a.arch
            if a == r.arch_all:
                br["Arch-All"] = "Yes"
            br["Build-Dep-Resolver"] = r.build_dep_resolver
            br["Apt-Allow-Unauthenticated"] = "1" if r.apt_allow_unauthenticated else "0"
            if r.lintian_mode != "disabled":
                # Generate lintian options
                br["Run-Lintian"] = {"never-fail": "", "fail-on-error": "", "fail-on-warning": "--fail-on-warning"}[r.lintian_mode] + " " + r.lintian_extra_options

            br.save()
            br_list.append(br)

        return br_list
