# -*- coding: utf-8 -*-
import os, stat, logging, tarfile, ftplib, re, contextlib

import debian.deb822

from mini_buildd import setup, misc

log = logging.getLogger(__name__)

class Changes(debian.deb822.Changes):
    BUILDREQUEST_RE = re.compile("^.+_mini-buildd-buildrequest_[^_]+.changes$")
    BUILDRESULT_RE = re.compile("^.+_mini-buildd-buildresult_[^_]+.changes$")

    def __init__(self, file_path):
        self._file_path = file_path
        self._file_name = os.path.basename(file_path)
        self._sha1 = misc.sha1_of_file(file_path) if os.path.exists(file_path) else None
        super(Changes, self).__init__(file(file_path) if os.path.exists(file_path) else [])
        # Be sure base dir is always available
        misc.mkdirs(os.path.dirname(file_path))

    def is_buildrequest(self):
        return self.BUILDREQUEST_RE.match(self._file_name)

    def is_buildresult(self):
        return self.BUILDRESULT_RE.match(self._file_name)

    def get(self, key):
        try:
            return self[key]
        except:
            return ""

    def get_repository(self):
        from models import Repository

        # Check and parse distribution
        dist = self["Distribution"]
        dist_s = self["Distribution"].split(u"-")
        if len(dist_s) != 3:
            raise Exception("Malformed distribution '{d}': Must be 'CODENAME-ID-SUITE'".format(d=dist))
        codename, identity, suite = dist_s[0], dist_s[1], dist_s[2]

        # Get repository for identity
        try:
            r = Repository.objects.get(identity=identity)
        except:
            raise Exception("Unsupported distribution '{d}': No such repository identity '{i}'".format(d=dist, i=identity))

        # Get distribution for codename
        found = False
        for d in r.distributions.all():
            if d.base_source.codename == dist_s[0]:
                found = True
                break
        if not found:
            raise Exception("Unsupported distribution '{d}': No such codename '{c}'".format(d=dist, c=codename))

        # Get uploadable suite
        found = False
        for s in r.layout.suites.all():
            if s.name == suite:
                found = True
                break
        if not found:
            raise Exception("Unsupported distribution '{d}': No such suite '{s}'".format(d=dist, s=suite))

        if s.migrates_from:
            raise Exception("Migrating distribution '{d}': You can't upload here".format(d=dist, s=suite))

        s.mbd_check_version(r, d, self["Version"])

        return r, d, s

    def get_spool_dir(self):
        return os.path.join(setup.SPOOL_DIR, self._sha1)

    def get_log_dir(self):
        return os.path.join(setup.LOG_DIR, self["Distribution"], self["Source"], self["Version"], self["Architecture"])

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
        log.info("FTP: Uploading changes: '{f}' to '{h}'...".format(f=self._file_name, h=host))
        ftp = ftplib.FTP()
        ftp.connect(host, port)
        ftp.login()
        ftp.cwd("/incoming")
        for fd in self.get_files() + [ {"name": self._file_name} ]:
            f = fd["name"]
            log.debug("FTP: Uploading file: '{f}'".format(f=f))
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

    def archive(self):
        logdir=self.get_log_dir()
        if not os.path.exists(logdir):
            os.makedirs(logdir)
        log.info("Moving changes to log: '{f}'->'{l}'".format(f=self._file_path, l=logdir))
        for fd in [ {"name": self._file_name} ] + self.get_files():
            f = os.path.join(os.path.dirname(self._file_path), fd["name"])
            log.debug("Moving: '{f}' to '{d}'". format(f=fd["name"], d=logdir))
            os.rename(f, os.path.join(logdir, fd["name"]))

    def remove(self):
        log.info("Removing changes: '{f}'".format(f=self._file_path))
        for fd in [ {"name": self._file_name} ] + self.get_files():
            f = os.path.join(os.path.dirname(self._file_path), fd["name"])
            log.debug("Removing: '{f}'".format(f=fd["name"]))
            os.remove(f)

    def gen_buildrequests(self, repository, dist):
        # Build buildrequest files for all architectures
        br_dict = {}
        for a in repository.architectures.all():
            path = os.path.join(self.get_spool_dir(), a.name)

            br = Changes(os.path.join(path, "{b}_mini-buildd-buildrequest_{a}.changes".format(b=self.get_pkg_id(), a=a.name)))
            for v in ["Distribution", "Source", "Version"]:
                br[v] = self[v]

            # Generate sources.list et.al. to be used
            open(os.path.join(path, "apt_sources.list"), 'w').write(repository.mbd_get_apt_sources_list(self["Distribution"]))
            open(os.path.join(path, "apt_preferences"), 'w').write(repository.mbd_get_apt_preferences())
            open(os.path.join(path, "apt_keys"), 'w').write(repository.mbd_get_apt_keys(self["Distribution"]))
            chroot_setup_script = os.path.join(path, "chroot_setup_script")
            open(chroot_setup_script, 'w').write(repository.mbd_get_chroot_setup_script(self["Distribution"]))
            os.chmod(chroot_setup_script, stat.S_IRWXU)
            open(os.path.join(path, "sbuildrc_snippet"), 'w').write(repository.mbd_get_sbuildrc_snippet(self["Distribution"], a.name))

            # Generate tar from original changes
            self.tar(tar_path=br._file_path + ".tar", add_files=[
                    os.path.join(path, "apt_sources.list"),
                    os.path.join(path, "apt_preferences"),
                    os.path.join(path, "apt_keys"),
                    chroot_setup_script,
                    os.path.join(path, "sbuildrc_snippet")])
            br.add_file(br._file_path + ".tar")

            br["Base-Distribution"] = dist.base_source.codename
            br["Architecture"] = a.name
            if a == repository.architecture_all:
                br["Arch-All"] = "Yes"
            br["Build-Dep-Resolver"] = repository.get_build_dep_resolver_display()
            br["Apt-Allow-Unauthenticated"] = "1" if repository.apt_allow_unauthenticated else "0"
            if repository.lintian_mode != repository.LINTIAN_DISABLED:
                # Generate lintian options
                modeargs = {
                    repository.LINTIAN_DISABLED:        "",
                    repository.LINTIAN_RUN_ONLY:        "",
                    repository.LINTIAN_FAIL_ON_ERROR:   "",
                    repository.LINTIAN_FAIL_ON_WARNING: "--fail-on-warning"}
                br["Run-Lintian"] = modeargs[repository.lintian_mode] + u" " + repository.lintian_extra_options

            br.save()
            br_dict[a.name] = br

        return br_dict
