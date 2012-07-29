# -*- coding: utf-8 -*-
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
    def __init__(self, breq):
        self._breq = breq
        self._started = datetime.datetime.now()
        self._done = None
        self._uploaded = None

    def __unicode__(self):
        return u"{s}: {c}: Started {start} ({took}), uploaded {uploaded}".format(
            s="DONE" if self._done else "BUILDING",
            c=self._breq,
            start=self._started,
            took=self._done - self._started if self._done else "n/a",
            uploaded=self._uploaded)

    def __str__(self):
        return self.__unicode__()

    def build(self):
        self._done = datetime.datetime.now()

    def uploaded(self):
        self._uploaded = datetime.datetime.now()


def buildlog_to_buildresult(file_name, bres):
    regex = re.compile("^[a-zA-Z0-9-]+: [^ ]+$")
    with open(file_name) as f:
        for l in f:
            if regex.match(l):
                LOG.debug("Build log line detected as build status: {l}".format(l=l.strip()))
                s = l.split(":")
                bres["Sbuild-" + s[0]] = s[1].strip()


def build_clean(breq):

    if "build" in mini_buildd.setup.DEBUG:
        LOG.warn("Build DEBUG mode -- not removing build spool dir {d}".format(d=breq.get_spool_dir()))
    else:
        shutil.rmtree(breq.get_spool_dir())
    breq.remove()


def generate_sbuildrc(path, breq):
    " Generate .sbuildrc for a build request (not all is configurable via switches, unfortunately)."

    with open(os.path.join(path, ".sbuildrc"), 'w') as f:
        # Automatic part part
        f.write("""\
# We update sources.list on the fly via chroot-setup commands;
# this update occurs before, so we don't need it.
$apt_update = 0;

# Allow unauthenticated apt toggle
$apt_allow_unauthenticated = {apt_allow_unauthenticated};

# Builder identity
$pgp_options = ['-us', '-k Mini-Buildd Automatic Signing Key'];
""".format(apt_allow_unauthenticated=breq["Apt-Allow-Unauthenticated"]))
        # Copy the custom snippet
        shutil.copyfileobj(open(os.path.join(path, "sbuildrc_snippet"), 'rb'), f)
        f.write("""
# don't remove this, Perl needs it:
1;
""")


def _build(breq, gnupg, sbuild_jobs):
    """
    .. todo:: Builder

       - Upload "internal error" result on exception to requesting mini-buildd.
       - DEB_BUILD_OPTIONS
       - [.sbuildrc] gpg setup
       - schroot bug: chroot-setup-command: uses sudo workaround
       - sbuild bug: long option '--jobs=N' does not work though advertised in man page (using '-jN')
    """
    mini_buildd.misc.sbuild_keys_workaround()

    build_dir = breq.get_spool_dir()

    bres = mini_buildd.changes.Changes(
        os.path.join(build_dir,
                     "{s}_{v}_mini-buildd-buildresult_{a}.changes".
                     format(s=breq["Source"], v=breq["Version"], a=breq["Architecture"])))

    if bres.is_new():
        breq.untar(path=build_dir)

        generate_sbuildrc(build_dir, breq)

        sbuild_cmd = ["sbuild",
                      "-j{0}".format(sbuild_jobs),
                      "--dist={0}".format(breq["Distribution"]),
                      "--arch={0}".format(breq["Architecture"]),
                      "--chroot=mini-buildd-{d}-{a}".format(d=breq["Base-Distribution"], a=breq["Architecture"]),
                      "--chroot-setup-command=sudo cp {p}/apt_sources.list /etc/apt/sources.list".format(p=build_dir),
                      "--chroot-setup-command=sudo cp {p}/apt_preferences /etc/apt/preferences".format(p=build_dir),
                      "--chroot-setup-command=sudo apt-key add {p}/apt_keys".format(p=build_dir),
                      "--chroot-setup-command=sudo apt-get update",
                      "--chroot-setup-command=sudo {p}/chroot_setup_script".format(p=build_dir),
                      "--build-dep-resolver={r}".format(r=breq["Build-Dep-Resolver"]),
                      "--nolog", "--log-external-command-output", "--log-external-command-error"]

        if "Arch-All" in breq:
            sbuild_cmd.append("--arch-all")
            sbuild_cmd.append("--source")
            sbuild_cmd.append("--debbuildopt=-sa")

        if "Run-Lintian" in breq:
            sbuild_cmd.append("--run-lintian")
            sbuild_cmd.append("--lintian-opts=--suppress-tags=bad-distribution-in-changes-file")
            sbuild_cmd.append("--lintian-opts={o}".format(o=breq["Run-Lintian"]))

        if "sbuild" in mini_buildd.setup.DEBUG:
            sbuild_cmd.append("--verbose")
            sbuild_cmd.append("--debug")

        sbuild_cmd.append("{s}_{v}.dsc".format(s=breq["Source"], v=breq["Version"]))

        buildlog = os.path.join(build_dir, "{s}_{v}_{a}.buildlog".format(s=breq["Source"], v=breq["Version"], a=breq["Architecture"]))
        LOG.info("{p}: Running sbuild: {c}".format(p=breq.get_pkg_id(with_arch=True), c=sbuild_cmd))
        with open(buildlog, "w") as l:
            retval = subprocess.call(sbuild_cmd,
                                     cwd=build_dir,
                                     env=mini_buildd.misc.taint_env({"HOME": build_dir}),
                                     stdout=l, stderr=subprocess.STDOUT)

        for v in ["Distribution", "Source", "Version", "Architecture"]:
            bres[v] = breq[v]

        # Add build results to build request object
        bres["Sbuildretval"] = str(retval)
        buildlog_to_buildresult(buildlog, bres)

        LOG.info("{p}: Sbuild finished: Sbuildretval={r}, Status={s}".format(p=breq.get_pkg_id(with_arch=True), r=retval, s=bres["Sbuild-Status"]))
        bres.add_file(buildlog)
        build_changes_file = os.path.join(build_dir,
                                          "{s}_{v}_{a}.changes".
                                          format(s=breq["Source"], v=breq["Version"], a=breq["Architecture"]))
        if os.path.exists(build_changes_file):
            build_changes = mini_buildd.changes.Changes(build_changes_file)
            build_changes.tar(tar_path=bres.file_path + ".tar")
            bres.add_file(bres.file_path + ".tar")

        bres.save(gnupg)
    else:
        LOG.info("Re-using existing buildresult: {b}".format(b=breq.file_name))

    return bres


def build(queue, builds, last_builds, gnupg, sbuild_jobs, breq):
    b = Build(breq)
    builds[breq.get_pkg_id(with_arch=True)] = b
    try:
        bres = _build(breq, gnupg, sbuild_jobs)
        b.build()
    except Exception as e:
        LOG.exception("Build internal error: {e}".format(e=str(e)))
        build_clean(breq)
        # todo: internal_error.upload(...)
    finally:
        queue.task_done()

    # Finally, try to upload to requesting mini-buildd; if the
    # upload fails, we keep all data and try later.
    try:
        bres.upload(mini_buildd.misc.HoPo(breq["Upload-Result-To"]))
        build_clean(breq)

        b.uploaded()
        last_builds.append(b)
        del builds[breq.get_pkg_id(with_arch=True)]
    except Exception as e:
        LOG.exception("Upload failed (trying later): {e}".format(e=str(e)))


def run(queue, builds, last_builds, gnupg, sbuild_jobs):
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
            gnupg=gnupg,
            sbuild_jobs=sbuild_jobs,
            breq=mini_buildd.changes.Changes(event))
