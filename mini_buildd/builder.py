# -*- coding: utf-8 -*-
import os, time, datetime, shutil, re, subprocess, logging

import django.db, django.core.exceptions

from mini_buildd import setup, changes, misc

log = logging.getLogger(__name__)

class Status(object):
    def __init__(self):
        self._builds = {}

    def start(self, key):
        # TODO: LOCK
        self._builds[key] = (time.time(), 0)

    def build(self, key):
        # TODO: LOCK
        start, build = self._builds[key]
        build = time.time()
        self._builds[key] = (start, build)

    def done(self, key):
        # TODO: LOCK
        del self._builds[key]

    def get_html(self):
        # TODO: LOCK
        def builds():
            builds = ""
            for key,value in self._builds.items():
                start, done = value
                builds += "<li><b>{s}</b>: {k} ({d})</li>".format(s="Building" if done == 0 else "Upload pending",
                                                                  k=key,
                                                                  d=datetime.datetime.fromtimestamp(start).strftime('%Y-%m-%d %H:%M:%S'))
            return builds

        return u"""\
<h4>{n} active builds</h4>
<ul>{b}</ul>
""".format(n=len(self._builds), b=builds())

def buildlog_to_buildresult(fn, bres):
    regex = re.compile("^[a-zA-Z0-9-]+: [^ ]+$")
    with open(fn) as f:
        for l in f:
            if regex.match(l):
                log.debug("Build log line detected as build status: {l}".format(l=l.strip()))
                s = l.split(":")
                bres["Sbuild-" + s[0]] = s[1].strip()

def build_clean(breq):
    if "build" in setup.DEBUG:
        log.warn("Build DEBUG mode -- not removing build spool dir {d}".format(d=breq.get_spool_dir()))
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

def build(breq, jobs, status):
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

    pkg_info = "{s}-{v}:{a}".format(s=breq["Source"], v=breq["Version"], a=breq["Architecture"])
    status.start(pkg_info)

    build_dir = breq.get_spool_dir()

    bres = changes.Changes(os.path.join(build_dir,
                                       "{s}_{v}_mini-buildd-buildresult_{a}.changes".
                                       format(s=breq["Source"], v=breq["Version"], a=breq["Architecture"])))

    if bres.is_new():
        try:
            breq.untar(path=build_dir)

            generate_sbuildrc(build_dir, breq)

            sbuild_cmd = ["sbuild",
                          "-j{0}".format(jobs),
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

            if "sbuild" in setup.DEBUG:
                sbuild_cmd.append("--verbose")
                sbuild_cmd.append("--debug")

            sbuild_cmd.append("{s}_{v}.dsc".format(s=breq["Source"], v=breq["Version"]))

            buildlog = os.path.join(build_dir, "{s}_{v}_{a}.buildlog".format(s=breq["Source"], v=breq["Version"], a=breq["Architecture"]))
            log.info("{p}: Running sbuild: {c}".format(p=pkg_info, c=sbuild_cmd))
            with open(buildlog, "w") as l:
                retval = subprocess.call(sbuild_cmd,
                                         cwd=build_dir,
                                         env=misc.taint_env({"HOME": build_dir}),
                                         stdout=l, stderr=subprocess.STDOUT)

            for v in ["Distribution", "Source", "Version", "Architecture"]:
                bres[v] = breq[v]

            # Add build results to build request object
            bres["Sbuildretval"] = str(retval)
            buildlog_to_buildresult(buildlog, bres)

            log.info("{p}: Sbuild finished: Sbuildretval={r}, Status={s}".format(p=pkg_info, r=retval, s=bres["Sbuild-Status"]))
            bres.add_file(buildlog)
            build_changes_file = os.path.join(build_dir,
                                              "{s}_{v}_{a}.changes".
                                              format(s=breq["Source"], v=breq["Version"], a=breq["Architecture"]))
            if os.path.exists(build_changes_file):
                build_changes = changes.Changes(build_changes_file)
                build_changes.tar(tar_path=bres._file_path + ".tar")
                bres.add_file(bres._file_path + ".tar")

            bres.save()
        except Exception as e:
            log.error("Build internal error: {e}".format(e=str(e)))
            build_clean(breq)
            # todo: internal_error.upload(...)
            return
    else:
        log.info("Re-using existing buildresult: {b}".format(b=breq._file_name))

    status.build(pkg_info)

    # Finally, try to upload to requesting mini-buildd; if the
    # upload fails, we keep all data and try later.
    try:
        bres.upload()
        build_clean(breq)
        status.done(pkg_info)
    except Exception as e:
        log.error("Upload failed (trying later): {e}".format(e=str(e)))

def run(queue, status, sbuild_jobs):
    while True:
        log.info("Builder status: {0} active builds, {0} waiting in queue.".
                 format(0, queue.qsize()))

        event = queue.get()
        if event == "SHUTDOWN":
            break
        misc.run_as_thread(build, daemon=True, breq=changes.Changes(event), jobs=sbuild_jobs, status=status)
        queue.task_done()
