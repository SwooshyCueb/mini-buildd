# -*- coding: utf-8 -*-
import os
import Queue
import logging
import tarfile
import ftplib
import re
import subprocess

import debian.deb822

import mini_buildd

log = logging.getLogger(__name__)

class Changes(debian.deb822.Changes):
    BUILDREQUEST_RE = re.compile("^.+_mini-buildd-buildrequest_[^_]+.changes$")
    BUILDRESULT_RE = re.compile("^.+_mini-buildd-buildresult_[^_]+.changes$")

    def __init__(self, file_path):
        self._file_path = file_path
        self._file_name = os.path.basename(file_path)
        super(Changes, self).__init__(file(file_path) if os.path.exists(file_path) else [])
        # Be sure base dir is always available
        mini_buildd.misc.mkdirs(os.path.dirname(file_path))

    def is_buildrequest(self):
        return self.BUILDREQUEST_RE.match(self._file_name)

    def is_buildresult(self):
        return self.BUILDRESULT_RE.match(self._file_name)

    def get_repository(self):
        from mini_buildd.models import Repository
        dist = self["Distribution"]
        r_id = dist.split("-")[1]
        log.debug(dist + "/" + r_id)

        r = Repository.objects.get(id=r_id)
        # @todo Check that base dist is really supported by this repo
        return r

    def get_spool_dir(self, base_dir):
        return os.path.join(base_dir, self["Distribution"], self["Source"], self["Version"], self["Buildrequest-Architecture"])

    def get_pkg_id(self):
        return "{s}_{v}".format(s=self["Source"], v=self["Version"])

    def get_files(self):
        return self["Files"] if "Files" in self else []

    def save(self, file_path=None):
        file_path = self._file_path if file_path == None else file_path

        log.info("Save {f}".format(f=file_path))
        self.dump(fd=open(file_path, "w+"))
        self._file_path = file_path
        self._file_name = os.path.basename(file_path)

    def upload(self, host="localhost", port=8067):
        ftp = ftplib.FTP()
        ftp.connect(host, port)
        ftp.login()
        ftp.cwd("/incoming")
        for fd in self.get_files() + [ {"name": self._file_name} ]:
            f = fd["name"]
            log.debug("FTP-Upload: '{f}'". format(f=f))
            try:
                ftp.list()
                ftp.size(f)
                log.warn("Already uploaded to this host: '{f}'...". format(f=f))
            except:
                ftp.storbinary("STOR {f}".format(f=f), open(os.path.join(os.path.dirname(self._file_path), f)))

    def tar(self, tar_path, add_files=[]):
        tar = tarfile.open(tar_path, "w")
        try:
            tar_add = lambda f: tar.add(f, arcname=os.path.basename(f))
            tar_add(self._file_path)
            for f in self.get_files():
                tar_add(os.path.join(os.path.dirname(self._file_path), f["name"]))
            for f in add_files:
                tar_add(f)
        finally:
            tar.close()

    def gen_buildrequests(self, base_dir):
        # Build buildrequest files for all archs
        br_list = []
        r = self.get_repository()
        for a in r.archs.all():
            path = os.path.join(base_dir, self["Distribution"], self["Source"], self["Version"], a.arch)
            br = Changes(os.path.join(path, "{b}_mini-buildd-buildrequest_{a}.changes".format(b=self.get_pkg_id(), a=a.arch)))
            for v in ["Distribution", "Source", "Version"]:
                br[v] = self[v]

            codename = br["Distribution"].split("-")[0]

            # Generate sources.list to be used
            open(os.path.join(path, "apt_sources.list"), 'w').write(r.get_apt_sources_list(self["Distribution"]))
            open(os.path.join(path, "apt_preferences"), 'w').write(r.get_apt_preferences())

            # Generate tar from original changes
            self.tar(tar_path=br._file_path + ".tar", add_files=[os.path.join(path, "apt_sources.list"), os.path.join(path, "apt_preferences")])
            # [ "md5sum", "size", "section", "priority", "name" ]
            br["Files"] = [{"md5sum": "FIXME", "size": "FIXME", "section": "mini-buildd-buildrequest", "priority": "FIXME", "name": br._file_name + ".tar"}]

            br["Buildrequest-Base-Distribution"] = codename
            br["Buildrequest-Architecture"] = a.arch
            if a == r.arch_all:
                br["Buildrequest-Arch-All"] = "Yes"
            br["Buildrequest-Build-Dep-Resolver"] = r.build_dep_resolver
            br["Buildrequest-Apt-Allow-Unauthenticated"] = "1" if r.apt_allow_unauthenticated else "0"
            if r.lintian_mode != "disabled":
                # Generate lintian options
                br["Buildrequest-Run-Lintian"] = {"never-fail": "", "fail-on-error": "", "fail-on-warning": "--fail-on-warning"}[r.lintian_mode] + " " + r.lintian_extra_options

            br.save()
            br_list.append(br)

        return br_list


class Build():
    def __init__(self, spool_dir, br):
        self._br = br
        self._spool_dir = spool_dir

    def results_from_buildlog(self, fn, changes):
        regex = re.compile("^[a-zA-Z0-9-]+: [^ ]+$")
        with open(fn) as f:
            for l in f:
                if regex.match(l):
                    log.debug("Build log line detected as build status: {l}".format(l=l.strip()))
                    s = l.split(":")
                    changes["Buildresult-Sbuild-" + s[0]] = s[1].strip()

    def run(self):
        # @todo Caveat: Create sbuild's internal key if needed. This should go somewhere else.
        if not os.path.exists("/var/lib/sbuild/apt-keys/sbuild-key.pub"):
            mini_buildd.misc.run_cmd("sbuild-update --keygen")

        pkg_info = "{s}-{v}:{a}".format(s=self._br["Source"], v=self._br["Version"], a=self._br["Buildrequest-Architecture"])

        path = self._br.get_spool_dir(self._spool_dir)

        tar = tarfile.open(self._br._file_path + ".tar", "r")
        try:
            tar.extractall(path=path)
        finally:
            tar.close()

        # @todo DEB_BUILD_OPTIONS

        # Generate .sbuildrc for this run (not all is configurable via switches).
        open(os.path.join(path, ".sbuildrc"), 'w').write("""
# Set "user" mode explicitely (already default).  Means the
# retval tells us if the sbuild run was ok. We also dont have to
# configure "mailto".
$sbuild_mode = 'user';

# We update sources.list on the fly via chroot-setup commands;
# this update occurs before, so we dont need it.
$apt_update = 0;

# Allow unauthenticated apt toggle
$apt_allow_unauthenticated = {apt_allow_unauthenticated};

# @todo: proper ccache support (was: Add path for ccache)
#$path = '/usr/lib/ccache:/usr/sbin:/usr/bin:/sbin:/bin:/usr/X11R6/bin:/usr/games';
##$build_environment = {{ 'CCACHE_DIR' => '$HOME/.ccache' }};

# @todo gpg setup
# Builder identity
$pgp_options = ['-us', '-k Mini-Buildd Automatic Signing Key'];

# don't remove this, Perl needs it:
1;
""".format(apt_allow_unauthenticated=self._br["Buildrequest-Apt-Allow-Unauthenticated"]))

        env = os.environ
        env["HOME"] = path

        ".. todo:: chroot-setup-command: uses sudo workaround (schroot bug)."
        sbuild_cmd = ["sbuild",
                      "--dist={0}".format(self._br["Distribution"]),
                      "--arch={0}".format(self._br["Buildrequest-Architecture"]),
                      "--chroot=mini-buildd-{d}-{a}".format(d=self._br["Buildrequest-Base-Distribution"], a=self._br["Buildrequest-Architecture"]),
                      "--chroot-setup-command=sudo cp {p}/apt_sources.list /etc/apt/sources.list".format(p=path),
                      "--chroot-setup-command=sudo cp {p}/apt_preferences /etc/apt/preferences".format(p=path),
                      "--chroot-setup-command=sudo apt-get update",
                      "--build-dep-resolver={r}".format(r=self._br["Buildrequest-Build-Dep-Resolver"]),
                      "--verbose", "--nolog", "--log-external-command-output", "--log-external-command-error"]

        if "Buildrequest-Arch-All" in self._br:
            sbuild_cmd.append("--arch-all")

        # @ todo lintian opt-in, repository options
        if "Run-Lintian" in self._br:
            sbuild_cmd.append("--run-lintian")
            sbuild_cmd.append("--lintian-opts=--suppress-tags=bad-distribution-in-changes-file")
            sbuild_cmd.append("--lintian-opts={o}".format(o=self._br["Buildrequest-Run-Lintian"]))

        if mini_buildd.globals.DEBUG:
            sbuild_cmd.append("--verbose")

        sbuild_cmd.append("{s}_{v}.dsc".format(s=self._br["Source"], v=self._br["Version"]))

        buildlog = os.path.join(path, "{s}_{v}_{a}.buildlog".format(s=self._br["Source"], v=self._br["Version"], a=self._br["Buildrequest-Architecture"]))
        log.info("{p}: Starting sbuild".format(p=pkg_info))
        log.debug("{p}: Sbuild options: {c}".format(p=pkg_info, c=sbuild_cmd))
        with open(buildlog, "w") as l:
            retval = subprocess.call(sbuild_cmd,
                                     cwd=path, env=env,
                                     stdout=l, stderr=subprocess.STDOUT)

        res = Changes(os.path.join(path,
                                   "{s}_{v}_mini-buildd-buildresult_{a}.changes".
                                   format(s=self._br["Source"], v=self._br["Version"], a=self._br["Buildrequest-Architecture"])))
        for v in ["Distribution", "Source", "Version"]:
            res[v] = self._br[v]

        # Add build results to build request object
        res["Buildresult-Retval"] = retval
        self.results_from_buildlog(buildlog, res)

        log.info("{p}: Sbuild finished: Retval={r}, Status={s}".format(p=pkg_info, r=retval, s=res["Buildresult-Sbuild-Status"]))
        res["Files"] = []
        res["Files"].append({"md5sum": "FIXME", "size": "FIXME", "section": "mini-buildd-buildresult", "priority": "FIXME", "name": os.path.basename(buildlog)})
        build_changes_file = os.path.join(path,
                                          "{s}_{v}_{a}.changes".
                                          format(s=self._br["Source"], v=self._br["Version"], a=self._br["Buildrequest-Architecture"]))
        if os.path.exists(build_changes_file):
            build_changes = Changes(build_changes_file)
            build_changes.tar(tar_path=res._file_path + ".tar")
            res["Files"].append({"md5sum": "FIXME", "size": "FIXME", "section": "mini-buildd-buildresult", "priority": "FIXME", "name": res._file_name + ".tar"})


        res.save()
        res.upload()


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
        self._builder = Builder(os.path.join(self._spool_dir, "builders"), self._build_queue)

    def run(self):
        mini_buildd.misc.start_thread(self._builder)
        while True:
            c = Changes(self._incoming_queue.get())
            if c.is_buildrequest():
                self._build_queue.put(c)
            elif c.is_buildresult():
                log.info("STUB: build result: '{f}'...".format(f=c._file_name))
            else:
                # User upload
                for br in c.gen_buildrequests(os.path.join(self._spool_dir, "repositories")):
                    br.upload()

            self._incoming_queue.task_done()
