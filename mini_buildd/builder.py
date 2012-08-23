# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import datetime
import shutil
import re
import subprocess
import logging

import mini_buildd.setup
import mini_buildd.misc
import mini_buildd.changes

LOG = logging.getLogger(__name__)


class Build(mini_buildd.misc.Status):
    FAILED = -1
    CHECKING = 0
    BUILDING = 1
    UPLOADING = 2
    UPLOADED = 10

    def __init__(self, breq, gnupg, sbuild_jobs):
        super(Build, self).__init__(
            stati={self.FAILED: "FAILED",
                   self.CHECKING: "CHECKING",
                   self.BUILDING: "BUILDING",
                   self.UPLOADING: "UPLOADING",
                   self.UPLOADED: "UPLOADED"})

        self._breq = breq
        self._gnupg = gnupg
        self._sbuild_jobs = sbuild_jobs

        self._build_dir = self._breq.get_spool_dir()
        self._chroot = "mini-buildd-{d}-{a}".format(d=self._breq["Base-Distribution"], a=self._breq["Architecture"])

        self._bres = breq.gen_buildresult()

        self.started = self._get_started_stamp()
        if self.started:
            self.set_status(self.BUILDING)

        self.built = self._get_built_stamp()
        if self.built:
            self.set_status(self.UPLOADING)

        self.uploaded = None

    def __unicode__(self):
        date_format = "%Y-%b-%d %H:%M:%S"
        return "[{h}] {k} ({c}): {s}: Started {start} ({took} seconds), uploaded {uploaded}.".format(
            h=self._breq["Upload-Result-To"],
            k=self.key,
            c=self._chroot,
            s=self.status,
            start=self.started.strftime(date_format),
            took=round(mini_buildd.misc.timedelta_total_seconds(self.built - self.started), 1) if self.built else "n/a",
            uploaded=self.uploaded.strftime(date_format) if self.uploaded else "n/a")

    @property
    def key(self):
        return self._breq.get_pkg_id(with_arch=True)

    @property
    def sbuildrc_path(self):
        return os.path.join(self._build_dir, ".sbuildrc")

    def _get_started_stamp(self):
        if os.path.exists(self.sbuildrc_path):
            return datetime.datetime.fromtimestamp(os.path.getmtime(self.sbuildrc_path))

    def _get_built_stamp(self):
        if os.path.exists(self._bres.file_path):
            return datetime.datetime.fromtimestamp(os.path.getmtime(self._bres.file_path))

    def _generate_sbuildrc(self):
        """
        Generate .sbuildrc for a build request (not all is configurable via switches, unfortunately).
        """
        mini_buildd.misc.ConfFile(
            self.sbuildrc_path,
            """\
# We update sources.list on the fly via chroot-setup commands;
# this update occurs before, so we don't need it.
$apt_update = 0;

# Allow unauthenticated apt toggle
$apt_allow_unauthenticated = {apt_allow_unauthenticated};

# Builder identity
$pgp_options = ['-us', '-k Mini-Buildd Automatic Signing Key'];

{custom_snippet}

# don't remove this, Perl needs it:
1;
""".format(apt_allow_unauthenticated=self._breq["Apt-Allow-Unauthenticated"],
           custom_snippet=open(os.path.join(self._build_dir, "sbuildrc_snippet"), 'rb').read())).save()

    def _buildlog_to_buildresult(self, buildlog):
        regex = re.compile("^[a-zA-Z0-9-]+: [^ ]+$")
        with open(buildlog) as f:
            for l in f:
                if regex.match(l):
                    LOG.debug("Build log line detected as build status: {l}".format(l=l.strip()))
                    s = l.split(":")
                    self._bres["Sbuild-" + s[0]] = s[1].strip()

    def build(self):
        """
        .. todo:: Builder

        - Upload "internal error" result on exception to requesting mini-buildd.
        - DEB_BUILD_OPTIONS
        - [.sbuildrc] gpg setup
        - schroot bug: chroot-setup-command: uses sudo workaround
        - sbuild bug: long option '--jobs=N' does not work though advertised in man page (using '-jN')
        """
        self._breq.untar(path=self._build_dir)
        self._generate_sbuildrc()
        self.started = self._get_started_stamp()

        sbuild_cmd = ["sbuild",
                      "-j{0}".format(self._sbuild_jobs),
                      "--dist={0}".format(self._breq["Distribution"]),
                      "--arch={0}".format(self._breq["Architecture"]),
                      "--chroot={c}".format(c=self._chroot),
                      "--chroot-setup-command=sudo cp {p}/apt_sources.list /etc/apt/sources.list".format(p=self._build_dir),
                      "--chroot-setup-command=cat /etc/apt/sources.list",
                      "--chroot-setup-command=sudo cp {p}/apt_preferences /etc/apt/preferences".format(p=self._build_dir),
                      "--chroot-setup-command=cat /etc/apt/preferences",
                      "--chroot-setup-command=sudo apt-key add {p}/apt_keys".format(p=self._build_dir),
                      "--chroot-setup-command=sudo apt-get update",
                      "--chroot-setup-command=sudo {p}/chroot_setup_script".format(p=self._build_dir),
                      "--build-dep-resolver={r}".format(r=self._breq["Build-Dep-Resolver"]),
                      "--nolog", "--log-external-command-output", "--log-external-command-error"]

        if "Arch-All" in self._breq:
            sbuild_cmd.append("--arch-all")
            sbuild_cmd.append("--source")
            sbuild_cmd.append("--debbuildopt=-sa")

        if "Run-Lintian" in self._breq:
            sbuild_cmd.append("--run-lintian")
            sbuild_cmd.append("--lintian-opts=--suppress-tags=bad-distribution-in-changes-file")
            sbuild_cmd.append("--lintian-opts={o}".format(o=self._breq["Run-Lintian"]))

        sbuild_cmd.append(self._breq.dsc_name)

        # Actually run sbuild
        mini_buildd.misc.sbuild_keys_workaround()
        buildlog = os.path.join(self._build_dir, self._breq.buildlog_name)
        LOG.info("{p}: Running sbuild: {c}".format(p=self.key, c=sbuild_cmd))
        with open(buildlog, "w") as l:
            retval = subprocess.call(sbuild_cmd,
                                     cwd=self._build_dir,
                                     env=mini_buildd.misc.taint_env({"HOME": self._build_dir}),
                                     stdout=l, stderr=subprocess.STDOUT)

        # Add build results to build request object
        self._bres["Sbuildretval"] = unicode(retval)
        self._buildlog_to_buildresult(buildlog)

        LOG.info("{p}: Sbuild finished: Sbuildretval={r}, Status={s}".format(p=self.key, r=retval, s=self._bres["Sbuild-Status"]))
        self._bres.add_file(buildlog)
        build_changes_file = os.path.join(self._build_dir,
                                          "{s}_{v}_{a}.changes".
                                          format(s=self._breq["Source"], v=self._breq["Version"], a=self._breq["Architecture"]))
        if os.path.exists(build_changes_file):
            build_changes = mini_buildd.changes.Changes(build_changes_file)
            build_changes.tar(tar_path=self._bres.file_path + ".tar")
            self._bres.add_file(self._bres.file_path + ".tar")

        self._bres.save(self._gnupg)
        self.built = self._get_built_stamp()

    def upload(self):
        hopo = mini_buildd.misc.HoPo(self._breq["Upload-Result-To"])
        self._bres.upload(hopo)
        self.uploaded = datetime.datetime.now()

    def clean(self):
        if "builder" in mini_buildd.setup.DEBUG:
            LOG.warn("BUILDER DEBUG MODE: Not removing build spool dir {d}".format(d=self._breq.get_spool_dir()))
        else:
            shutil.rmtree(self._breq.get_spool_dir())
        self._breq.remove()


class LastBuild(mini_buildd.misc.API):
    __API__ = -100

    def __init__(self, build):
        super(LastBuild, self).__init__()
        self.identity = build.__unicode__()

    def __unicode__(self):
        return self.identity


def build(queue, builds, last_builds, remotes_keyring, gnupg, sbuild_jobs, breq):
    try:
        # Always authorize the file first
        remotes_keyring.verify(breq.file_path)

        # First, get build object. This will automagically set the status right.
        b = Build(breq, gnupg, sbuild_jobs)
        builds[b.key] = b

        # Build if needed (may be just an upload-pending build)
        if b.get_status() < b.BUILDING:
            b.set_status(b.BUILDING)
            b.build()
            b.set_status(b.UPLOADING)

        # Try upload
        try:
            b.upload()
            b.set_status(b.UPLOADED)
            del builds[b.key]
            b.clean()
            last_builds.appendleft(LastBuild(b))
        except Exception as e:
            b.set_status(b.UPLOADING, unicode(e))
    except Exception as e:
        # todo: upload error result
        pass
    finally:
        queue.task_done()


def run(queue, builds, last_builds, remotes_keyring, gnupg, sbuild_jobs):
    while True:
        event = queue.get()
        if event == "SHUTDOWN":
            break

        LOG.info("Builder status: {s}.".format(s=queue))

        mini_buildd.misc.run_as_thread(
            build,
            daemon=True,
            queue=queue,
            builds=builds,
            last_builds=last_builds,
            remotes_keyring=remotes_keyring,
            gnupg=gnupg,
            sbuild_jobs=sbuild_jobs,
            breq=mini_buildd.changes.Changes(event))
