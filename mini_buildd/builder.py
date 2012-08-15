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


class Build(object):
    __API__ = 0
# pylint: disable=R0801
    CHECKING = "CHECKING"
    REJECTED = "REJECTED"
    BUILDING = "BUILDING"
    FAILED = "FAILED"
    BUILT = "BUILT"
    UPLOADED = "UPLOADED"
# pylint: enable=R0801

    def __init__(self, breq, gnupg, sbuild_jobs):
        super(Build, self).__init__()

        self._status = self.CHECKING
        self._status_desc = "."

        self._breq = breq
        self._gnupg = gnupg
        self._sbuild_jobs = sbuild_jobs

        self._build_dir = self._breq.get_spool_dir()

        self._bres = breq.gen_buildresult()

        self.started = self._get_started_stamp()
        if self.started:
            self._status = self.BUILDING
        self.built = self._get_built_stamp()
        if self.built:
            self._status = self.BUILT

        self.uploaded = None
        self.upload_error = "None"

    def __unicode__(self):
        return "{s}: {k}: Started {start} ({took}), uploaded {uploaded}: {desc}".format(
            s=self._status,
            k=self.key,
            start=self.started,
            took=self.built - self.started if self.built else "n/a",
            uploaded=self.uploaded if self.uploaded else self.upload_error,
            desc=self._status_desc)

    def set_status(self, status, desc="."):
        self._status = status
        self._status_desc = desc

    @property
    def key(self):
        return self._breq.get_pkg_id(with_arch=True)

    @property
    def status(self):
        if self.uploaded:
            return "DONE"
        elif self.built:
            return "UPLOAD PENDING"
        else:
            return "BUILDING"

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
                      "--chroot=mini-buildd-{d}-{a}".format(d=self._breq["Base-Distribution"], a=self._breq["Architecture"]),
                      "--chroot-setup-command=sudo cp {p}/apt_sources.list /etc/apt/sources.list".format(p=self._build_dir),
                      "--chroot-setup-command=sudo cp {p}/apt_preferences /etc/apt/preferences".format(p=self._build_dir),
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

    def try_upload(self):
        hopo = mini_buildd.misc.HoPo(self._breq["Upload-Result-To"])
        try:
            self._bres.upload(hopo)
            self.uploaded = datetime.datetime.now()
            return True
        except Exception as e:
            self.upload_error = "{e}".format(e=e)
            mini_buildd.setup.log_exception(LOG, "Upload to '{h}' failed".format(h=hopo.string), e)

    def clean(self):
        if "builder" in mini_buildd.setup.DEBUG:
            LOG.warn("BUILDER DEBUG MODE: Not removing build spool dir {d}".format(d=self._breq.get_spool_dir()))
        else:
            shutil.rmtree(self._breq.get_spool_dir())
        self._breq.remove()


def build(queue, builds, last_builds, remotes_keyring, gnupg, sbuild_jobs, breq):
    remotes_keyring.verify(breq.file_path)

    # Get build object
    b = Build(breq, gnupg, sbuild_jobs)

    # Build if needed (may be just an upload-pending build)
    if not b.built:
        builds[b.key] = b
        b.build()
    queue.task_done()

    # Try upload
    b.try_upload()
    if b.uploaded:
        b.clean()
        last_builds.appendleft(b)
        del builds[b.key]


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
