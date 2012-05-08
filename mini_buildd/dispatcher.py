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
    def __init__(self, file_path, spool_dir):
        self._file_path = file_path
        self._file_name = os.path.basename(file_path)

        if os.path.exists(file_path):
            super(Changes, self).__init__(file(file_path))
            self._spool_dir = os.path.join(spool_dir, self["Distribution"], self["Source"], self["Version"], self["Architecture"])
        else:
            super(Changes, self).__init__([])
            self._spool_dir = None

    def save(self, file_path=None):
        file_path = self._file_path if file_path == None else file_path

        log.info("Save {f}".format(f=file_path))
        self.dump(fd=open(file_path, "w+"))
        self._file_path = file_path
        self._file_name = os.path.basename(file_path)

    def get_file_name(self, new_ext=None):
        if new_ext == None:
            return self._file_name
        else:
            return os.path.splitext(self._file_name)[0] + new_ext

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
        tar = tarfile.open(self._tar_path, "r")
        tar.extractall(path=self._spool_dir)
        tar.close()
        return self._spool_dir

class SourceChanges(Changes):
    def __init__(self, file_path, spool_dir):
        super(SourceChanges, self).__init__(file_path, spool_dir)
        self._base_spool_dir = spool_dir

        # @todo: If uploaded input, check it does not exist yet
        mini_buildd.misc.mkdirs(self._spool_dir)

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
        r = self.get_repository()
        for a in r.archs.all():
            brf = "{b}_{a}.buildrequest".format(b=self._tar_path, a=a.arch)
            br = Buildrequest(brf, self._base_spool_dir)
            # @todo Add all build information from repository
            for v in ["Distribution", "Source", "Version"]:
                br[v] = self[v]
            br["Base-Distribution"] = br["Distribution"].split("-")[0]
            br["Architecture"] = a.arch
            br["Build-Dep-Resolver"] = r.build_dep_resolver
            br["Apt-Allow-Unauthenticated"] = "1" if r.apt_allow_unauthenticated else "0"
            if r.lintian_mode != "disabled":
                # Generate lintian options
                br["Run-Lintian"] = {"never-fail": "", "fail-on-error": "", "fail-on-warning": "--fail-on-warning"}[r.lintian_mode] + " " + r.lintian_extra_options

            br.save()
            br_list.append(br)

        return br_list


class Build():
    def __init__(self, spool_dir, f):
        self._br = Buildrequest(f, spool_dir)
        self._spool_dir = spool_dir

    def results_from_buildlog(self, fn):
        regex = re.compile("^[a-zA-Z0-9-]+: [^ ]+$")
        with open(fn) as f:
            for l in f:
                if regex.match(l):
                    log.debug("Build log line detected as build status: {l}".format(l=l.strip()))
                    s = l.split(":")
                    self._br["Buildresult-Sbuild-" + s[0]] = s[1].strip()

    def run(self):
        # @todo Caveat: Create sbuild's internal key if needed. This should go somewhere else.
        if not os.path.exists("/var/lib/sbuild/apt-keys/sbuild-key.pub"):
            mini_buildd.misc.run_cmd("sbuild-update --keygen")

        pkg_info = "{s}-{v}:{a}".format(s=self._br["Source"], v=self._br["Version"], a=self._br["Architecture"])

        path = self._br.unpack()

        # @todo
        #if DEB_BUILD_OPTIONS="${mbdParseArch_debopts}"

        # Run sbuild. Notes:
        # * DEB_BUILD_OPTIONS are configured per build host.
        # Generate .sbuildrc for this run (not all is configurable via switches).
        open(os.path.join(path, ".sbuildrc"), 'w').write("""
# Set "user" mode explicitely (already default).  Means the
# retval tells us if the sbuild run was ok. We also dont have to
# configure "mailto".
$sbuild_mode = 'user';

# @todo sources.list generation.
# We always want to update the cache as we generate sources.list on the fly.
$apt_update = 1;

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
""".format(apt_allow_unauthenticated=self._br["Apt-Allow-Unauthenticated"]))

        env = os.environ
        env["HOME"] = path

        sbuild_cmd = ["sbuild",
                      "--dist={0}".format(self._br["Distribution"]),
                      "--arch={0}".format(self._br["Architecture"]),
                      "--chroot=mini-buildd-{d}-{a}".format(d=self._br["Base-Distribution"], a=self._br["Architecture"]),
                      "--build-dep-resolver={r}".format(r=self._br["Build-Dep-Resolver"]),
                      "--verbose", "--nolog", "--log-external-command-output", "--log-external-command-error"]

        # @ todo lintian opt-in, repository options
        if "Run-Lintian" in self._br:
            sbuild_cmd.append("--run-lintian")
            sbuild_cmd.append("--lintian-opts=--suppress-tags=bad-distribution-in-changes-file")
            sbuild_cmd.append("--lintian-opts={o}".format(o=self._br["Run-Lintian"]))

        if mini_buildd.globals.DEBUG:
            sbuild_cmd.append("--debug")

        sbuild_cmd.append("{s}_{v}.dsc".format(s=self._br["Source"], v=self._br["Version"]))

        buildlog = os.path.join(path, "{s}_{v}_{a}.buildlog".format(s=self._br["Source"], v=self._br["Version"], a=self._br["Architecture"]))
        log.info("{p}: Starting sbuild".format(p=pkg_info))
        log.debug("{p}: Sbuild options: {c}".format(p=pkg_info, c=sbuild_cmd))
        with open(buildlog, "w") as l:
            retval = subprocess.call(sbuild_cmd,
                                     cwd=path, env=env,
                                     stdout=l, stderr=subprocess.STDOUT)

        # Add build results to build request object
        self._br["Buildresult-Retval"] = retval
        self.results_from_buildlog(buildlog)

        log.info("{p}: Sbuild finished: Retval={r}, Status={s}".format(p=pkg_info, r=retval, s=self._br["Buildresult-Sbuild-Status"]))

        if self._br["Buildresult-Sbuild-Status"] != "skipped":
            build_changes = SourceChanges(os.path.join(
                    path,
                    "{s}_{v}_{a}.changes".
                    format(s=self._br["Source"], v=self._br["Version"], a=self._br["Architecture"])),
                                          self._spool_dir)

        self._br.save(os.path.join(
                path,
                "{s}_{v}_{a}.changes.tar_{a}.buildresult".
                format(s=self._br["Source"], v=self._br["Version"], a=self._br["Architecture"])))


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
            f = self._incoming_queue.get()
            ext = os.path.splitext(f)[1]
            if ext == ".changes":
                # User upload
                c = SourceChanges(f, os.path.join(self._spool_dir, "repositories"))
                for br in c.gen_build_requests():
                    br.upload()

            elif ext == ".buildrequest":
                self._build_queue.put(f)
            elif ext == ".buildresult":
                log.info("STUB: build result: '{f}'...".format(f=f))
            else:
                raise Exception("Internal error: Wrong incoming file {f}".format(f=f))

            self._incoming_queue.task_done()
