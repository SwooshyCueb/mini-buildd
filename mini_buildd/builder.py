# -*- coding: utf-8 -*-
import os, shutil, re, subprocess, logging

import django.db, django.core.exceptions

from mini_buildd import setup, changes, misc

log = logging.getLogger(__name__)

def results_from_buildlog(fn, changes):
    regex = re.compile("^[a-zA-Z0-9-]+: [^ ]+$")
    with open(fn) as f:
        for l in f:
            if regex.match(l):
                log.debug("Build log line detected as build status: {l}".format(l=l.strip()))
                s = l.split(":")
                changes["Sbuild-" + s[0]] = s[1].strip()

def build_clean(br):
    shutil.rmtree(br.get_spool_dir())
    br.remove()

def build(br, jobs):
    """
    .. todo:: Builder

       - Upload "internal error" result on exception to requesting mini-buildd.
       - DEB_BUILD_OPTIONS
       - [.sbuildrc] proper ccache support (was: Add path for ccache)
       - [.sbuildrc] gpg setup
       - schroot bug: chroot-setup-command: uses sudo workaround
       - sbuild bug: long option '--jobs=N' does not work though advertised in man page (using '-jN')
    """
    misc.sbuild_keys_workaround()

    pkg_info = "{s}-{v}:{a}".format(s=br["Source"], v=br["Version"], a=br["Architecture"])

    build_dir = br.get_spool_dir()
    try:
        br.untar(path=build_dir)

        # Generate .sbuildrc for this run (not all is configurable via switches).
        open(os.path.join(build_dir, ".sbuildrc"), 'w').write("""
# Set "user" mode explicitely (already default).  Means the
# retval tells us if the sbuild run was ok. We also dont have to
# configure "mailto".
$sbuild_mode = 'user';

# We update sources.list on the fly via chroot-setup commands;
# this update occurs before, so we dont need it.
$apt_update = 0;

# Allow unauthenticated apt toggle
$apt_allow_unauthenticated = {apt_allow_unauthenticated};

#$path = '/usr/lib/ccache:/usr/sbin:/usr/bin:/sbin:/bin:/usr/X11R6/bin:/usr/games';
##$build_environment = {{ 'CCACHE_DIR' => '$HOME/.ccache' }};

# Builder identity
$pgp_options = ['-us', '-k Mini-Buildd Automatic Signing Key'];

# don't remove this, Perl needs it:
1;
""".format(apt_allow_unauthenticated=br["Apt-Allow-Unauthenticated"]))

        sbuild_cmd = ["sbuild",
                      "-j{0}".format(jobs),
                      "--dist={0}".format(br["Distribution"]),
                      "--arch={0}".format(br["Architecture"]),
                      "--chroot=mini-buildd-{d}-{a}".format(d=br["Base-Distribution"], a=br["Architecture"]),
                      "--chroot-setup-command=sudo cp {p}/apt_sources.list /etc/apt/sources.list".format(p=build_dir),
                      "--chroot-setup-command=sudo cp {p}/apt_preferences /etc/apt/preferences".format(p=build_dir),
                      "--chroot-setup-command=sudo apt-key add {p}/apt_keys".format(p=build_dir),
                      "--chroot-setup-command=sudo apt-get update",
                      "--chroot-setup-command=sudo {p}/chroot_setup_script".format(p=build_dir),
                      "--build-dep-resolver={r}".format(r=br["Build-Dep-Resolver"]),
                      "--nolog", "--log-external-command-output", "--log-external-command-error"]

        if "Arch-All" in br:
            sbuild_cmd.append("--arch-all")
            sbuild_cmd.append("--source")
            sbuild_cmd.append("--debbuildopt=-sa")

        if "Run-Lintian" in br:
            sbuild_cmd.append("--run-lintian")
            sbuild_cmd.append("--lintian-opts=--suppress-tags=bad-distribution-in-changes-file")
            sbuild_cmd.append("--lintian-opts={o}".format(o=br["Run-Lintian"]))

        if setup.DEBUG:
            sbuild_cmd.append("--verbose")
            sbuild_cmd.append("--chroot-setup-command=env")

        sbuild_cmd.append("{s}_{v}.dsc".format(s=br["Source"], v=br["Version"]))

        buildlog = os.path.join(build_dir, "{s}_{v}_{a}.buildlog".format(s=br["Source"], v=br["Version"], a=br["Architecture"]))
        log.info("{p}: Running sbuild: {c}".format(p=pkg_info, c=sbuild_cmd))
        with open(buildlog, "w") as l:
            retval = subprocess.call(sbuild_cmd,
                                     cwd=build_dir, env=misc.taint_env({"HOME": build_dir}),
                                     stdout=l, stderr=subprocess.STDOUT)

        res = changes.Changes(os.path.join(build_dir,
                                           "{s}_{v}_mini-buildd-buildresult_{a}.changes".
                                           format(s=br["Source"], v=br["Version"], a=br["Architecture"])))
        for v in ["Distribution", "Source", "Version", "Architecture"]:
            res[v] = br[v]

        # Add build results to build request object
        res["Sbuildretval"] = str(retval)
        results_from_buildlog(buildlog, res)

        log.info("{p}: Sbuild finished: Sbuildretval={r}, Status={s}".format(p=pkg_info, r=retval, s=res["Sbuild-Status"]))
        res.add_file(buildlog)
        build_changes_file = os.path.join(build_dir,
                                          "{s}_{v}_{a}.changes".
                                          format(s=br["Source"], v=br["Version"], a=br["Architecture"]))
        if os.path.exists(build_changes_file):
            build_changes = changes.Changes(build_changes_file)
            build_changes.tar(tar_path=res._file_path + ".tar")
            res.add_file(res._file_path + ".tar")

        res.save()
    except Exception as e:
        log.error("Build internal error: {e}".format(e=str(e)))
        build_clean(br)
        # todo: internal_error.upload(...)
        return

    # Finally, try to upload to requesting mini-buildd; if the
    # upload fails, we keep all data and try later.
    try:
        res.upload()
    except Exception as e:
        log.error("Upload failed (trying later): {e}".format(e=str(e)))

    # Success, cleanup spool and incoming
    build_clean(br)

def run(build_queue, sbuild_jobs):
    """
    .. todo:: Builder

      - Upload retry.
    """
    builds = []
    while True:
        log.info("Builder status: {0} active builds, {0} waiting in queue.".
                 format(len(builds), build_queue.qsize()))

        event = build_queue.get()
        if event == "SHUTDOWN":
            break

        builds.append(misc.run_as_thread(build, br=changes.Changes(event), jobs=sbuild_jobs))
        build_queue.task_done()

    for t in builds:
        log.debug("Waiting for build: {i}".format(i=t))
        t.join()
