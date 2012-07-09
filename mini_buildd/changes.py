# -*- coding: utf-8 -*-
import os
import stat
import logging
import tarfile
import ftplib
import re
import contextlib

import debian.deb822

import mini_buildd.setup
import mini_buildd.misc
import mini_buildd.gnupg

log = logging.getLogger(__name__)

class Changes(debian.deb822.Changes):
    BUILDREQUEST_RE = re.compile("^.+_mini-buildd-buildrequest_[^_]+.changes$")
    BUILDRESULT_RE = re.compile("^.+_mini-buildd-buildresult_[^_]+.changes$")

    def __init__(self, file_path):
        self._file_path = file_path
        self._file_name = os.path.basename(file_path)
        self._new = not os.path.exists(file_path)
        self._sha1 = None if self._new else mini_buildd.misc.sha1_of_file(file_path)
        super(Changes, self).__init__([] if self._new else file(file_path))
        # Be sure base dir is always available
        mini_buildd.misc.mkdirs(os.path.dirname(file_path))

    def is_new(self):
        return self._new

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
        from mini_buildd.models import Repository

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
        return os.path.join(mini_buildd.setup.SPOOL_DIR, self._sha1)

    def get_log_dir(self):
        return os.path.join(mini_buildd.setup.LOG_DIR, self["Distribution"], self["Source"], self["Version"], self["Architecture"])

    def get_pkg_id(self):
        return "{s}_{v}".format(s=self["Source"], v=self["Version"])

    def get_files(self):
        return self["Files"] if "Files" in self else []

    def add_file(self, fn):
        if not "Files" in self:
            self["Files"] = []
        self["Files"].append({"md5sum": mini_buildd.misc.md5_of_file(fn),
                              "size": os.path.getsize(fn),
                              "section": "mini-buildd",
                              "priority": "extra",
                              "name": os.path.basename(fn)})

    def save(self):
        try:
            log.info("Saving changes: {f}".format(f=self._file_path))
            self.dump(fd=open(self._file_path, "w+"))
            log.info("Signing changes: {f}".format(f=self._file_path))
            import mini_buildd.daemon
            mini_buildd.daemon.get().model._gnupg.sign(self._file_path)
        except:
            # Existence of the file name is used as flag
            if os.path.exists(self._file_path):
                os.remove(self._file_path)
            raise

    def authenticate_against_remotes(self):
        ".. todo:: Actually authenticate against remotes"
        import mini_buildd.daemon
        mini_buildd.daemon.get().model._gnupg.verify(self._file_path)

    def authenticate_against_users(self, repository):
        if repository.allow_unauthenticated_uploads:
            log.warn("Unauthenticated uploads allowed. Using '{c}' unchecked".format(c=self._file_name))
        else:
            import django.contrib.auth.models
            gpg = mini_buildd.gnupg.TmpGnuPG()
            for u in django.contrib.auth.models.User.objects.all():
                p = u.get_profile()
                for r in p.may_upload_to.all():
                    if r.identity == repository.identity:
                        gpg.add_pub_key(p.key)
                        log.info(u"Uploader key added for '{r}': {k}: {n}".format(r=repository, k=p.key_long_id, n=p.key_name))
            gpg.verify(self._file_path)

    def upload(self, host="localhost", port=8067):
        upload = os.path.splitext(self._file_path)[0] + ".upload"
        if os.path.exists(upload):
            log.info("FTP: '{f}' already uploaded to '{h}'...".format(f=self._file_name, h=open(upload).read()))
        else:
            ftp = ftplib.FTP()
            ftp.connect(host, port)
            ftp.login()
            ftp.cwd("/incoming")
            for fd in self.get_files() + [ {"name": self._file_name} ]:
                f = fd["name"]
                log.debug("FTP: Uploading file: '{f}'".format(f=f))
                ftp.storbinary("STOR {f}".format(f=f), open(os.path.join(os.path.dirname(self._file_path), f)))
            open(upload, "w").write("{h}:{p}".format(h=host, p=port))
            log.info("FTP: '{f}' uploaded to '{h}'...".format(f=self._file_name, h=host))

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
        logdir = self.get_log_dir()
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
        breq_dict = {}
        for a in dist.mbd_get_all_architectures():
            path = os.path.join(self.get_spool_dir(), a)

            breq = Changes(os.path.join(path, "{b}_mini-buildd-buildrequest_{a}.changes".format(b=self.get_pkg_id(), a=a)))
            if breq.is_new():
                for v in ["Distribution", "Source", "Version"]:
                    breq[v] = self[v]

                # Generate sources.list et.al. to be used
                open(os.path.join(path, "apt_sources.list"), 'w').write(repository.mbd_get_apt_sources_list(self["Distribution"]))
                open(os.path.join(path, "apt_preferences"), 'w').write(repository.mbd_get_apt_preferences())
                open(os.path.join(path, "apt_keys"), 'w').write(repository.mbd_get_apt_keys(self["Distribution"]))
                chroot_setup_script = os.path.join(path, "chroot_setup_script")
                open(chroot_setup_script, 'w').write(repository.mbd_get_chroot_setup_script(self["Distribution"]))
                os.chmod(chroot_setup_script, stat.S_IRWXU)
                open(os.path.join(path, "sbuildrc_snippet"), 'w').write(repository.mbd_get_sbuildrc_snippet(self["Distribution"], a))

                # Generate tar from original changes
                self.tar(tar_path=breq._file_path + ".tar", add_files=[
                        os.path.join(path, "apt_sources.list"),
                        os.path.join(path, "apt_preferences"),
                        os.path.join(path, "apt_keys"),
                        chroot_setup_script,
                        os.path.join(path, "sbuildrc_snippet")])
                breq.add_file(breq._file_path + ".tar")

                breq["Base-Distribution"] = dist.base_source.codename
                breq["Architecture"] = a
                if a == dist.architecture_all.name:
                    breq["Arch-All"] = "Yes"
                breq["Build-Dep-Resolver"] = dist.get_build_dep_resolver_display()
                breq["Apt-Allow-Unauthenticated"] = "1" if dist.apt_allow_unauthenticated else "0"
                if dist.lintian_mode != dist.LINTIAN_DISABLED:
                    # Generate lintian options
                    modeargs = {
                        dist.LINTIAN_DISABLED:        "",
                        dist.LINTIAN_RUN_ONLY:        "",
                        dist.LINTIAN_FAIL_ON_ERROR:   "",
                        dist.LINTIAN_FAIL_ON_WARNING: "--fail-on-warning"}
                    breq["Run-Lintian"] = modeargs[dist.lintian_mode] + u" " + dist.lintian_extra_options

                breq.save()
            else:
                log.info("Re-using existing buildrequest: {b}".format(b=breq._file_name))
            breq_dict[a] = breq

        return breq_dict
