# -*- coding: utf-8 -*-
import os, re, subprocess, logging

import django.db, django.core.exceptions

from mini_buildd import setup, changes, misc

from mini_buildd.models import Chroot

log = logging.getLogger(__name__)

def results_from_buildlog(fn, changes):
    regex = re.compile("^[a-zA-Z0-9-]+: [^ ]+$")
    with open(fn) as f:
        for l in f:
            if regex.match(l):
                log.debug("Build log line detected as build status: {l}".format(l=l.strip()))
                s = l.split(":")
                changes["Sbuild-" + s[0]] = s[1].strip()

def build(br):
    """
    .. todo:: Builder

       - DEB_BUILD_OPTIONS
       - [.sbuildrc] proper ccache support (was: Add path for ccache)
       - [.sbuildrc] gpg setup
       - chroot-setup-command: uses sudo workaround (schroot bug).
    """
    misc.sbuild_keys_workaround()

    pkg_info = "{s}-{v}:{a}".format(s=br["Source"], v=br["Version"], a=br["Architecture"])

    path = br.get_spool_dir(setup.BUILDS_DIR)
    br.untar(path=path)

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

#$path = '/usr/lib/ccache:/usr/sbin:/usr/bin:/sbin:/bin:/usr/X11R6/bin:/usr/games';
##$build_environment = {{ 'CCACHE_DIR' => '$HOME/.ccache' }};

# Builder identity
$pgp_options = ['-us', '-k Mini-Buildd Automatic Signing Key'];

# don't remove this, Perl needs it:
1;
""".format(apt_allow_unauthenticated=br["Apt-Allow-Unauthenticated"]))

    sbuild_cmd = ["sbuild",
                  "--dist={0}".format(br["Distribution"]),
                  "--arch={0}".format(br["Architecture"]),
                  "--chroot=mini-buildd-{d}-{a}".format(d=br["Base-Distribution"], a=br["Architecture"]),
                  "--chroot-setup-command=sudo cp {p}/apt_sources.list /etc/apt/sources.list".format(p=path),
                  "--chroot-setup-command=sudo cp {p}/apt_preferences /etc/apt/preferences".format(p=path),
                  "--chroot-setup-command=sudo apt-get update",
                  "--build-dep-resolver={r}".format(r=br["Build-Dep-Resolver"]),
                  "--verbose", "--nolog", "--log-external-command-output", "--log-external-command-error"]

    if "Arch-All" in br:
        sbuild_cmd.append("--arch-all")
        sbuild_cmd.append("--source")

    if "Run-Lintian" in br:
        sbuild_cmd.append("--run-lintian")
        sbuild_cmd.append("--lintian-opts=--suppress-tags=bad-distribution-in-changes-file")
        sbuild_cmd.append("--lintian-opts={o}".format(o=br["Run-Lintian"]))

    if setup.DEBUG:
        sbuild_cmd.append("--verbose")

    sbuild_cmd.append("{s}_{v}.dsc".format(s=br["Source"], v=br["Version"]))

    buildlog = os.path.join(path, "{s}_{v}_{a}.buildlog".format(s=br["Source"], v=br["Version"], a=br["Architecture"]))
    log.info("{p}: Starting sbuild".format(p=pkg_info))
    log.debug("{p}: Sbuild options: {c}".format(p=pkg_info, c=sbuild_cmd))
    with open(buildlog, "w") as l:
        retval = subprocess.call(sbuild_cmd,
                                 cwd=path, env=misc.taint_env({"HOME": path}),
                                 stdout=l, stderr=subprocess.STDOUT)

    res = changes.Changes(os.path.join(path,
                                       "{s}_{v}_mini-buildd-buildresult_{a}.changes".
                                       format(s=br["Source"], v=br["Version"], a=br["Architecture"])))
    for v in ["Distribution", "Source", "Version"]:
        res[v] = br[v]

    # Add build results to build request object
    res["Sbuildretval"] = str(retval)
    results_from_buildlog(buildlog, res)

    log.info("{p}: Sbuild finished: Sbuildretval={r}, Status={s}".format(p=pkg_info, r=retval, s=res["Sbuild-Status"]))
    res.add_file(buildlog)
    build_changes_file = os.path.join(path,
                                      "{s}_{v}_{a}.changes".
                                      format(s=br["Source"], v=br["Version"], a=br["Architecture"]))
    if os.path.exists(build_changes_file):
        build_changes = changes.Changes(build_changes_file)
        build_changes.tar(tar_path=res._file_path + ".tar")
        res.add_file(res._file_path + ".tar")

    res.save()
    res.upload()


class Builder(django.db.models.Model):
    max_parallel_builds = django.db.models.IntegerField(
        default=4,
        help_text="Maximum number of parallel builds.")

    sbuild_parallel = django.db.models.IntegerField(
        default=1,
        help_text="Degree of parallelism per build.")

    def __unicode__(self):
        res = "Builder for: "
        for c in Chroot.objects.all():
            res += c.__unicode__() + ", "
        return res

    def clean(self):
        super(Builder, self).clean()
        if Builder.objects.count() > 0 and self.id != Builder.objects.get().id:
            raise django.core.exceptions.ValidationError("You can only create one Builder instance!")

django.contrib.admin.site.register(Builder)


def run(build_queue):
    builder, created = Builder.objects.get_or_create(id=1)

    join_threads = []
    while True:
        event = build_queue.get()
        if event == "SHUTDOWN":
            break
        c = changes.Changes(event)
        join_threads.append(misc.run_as_thread(build, br=c))
        build_queue.task_done()

    log.info("{d}: Shutting down...".format(d=builder))
    for t in join_threads:
        log.debug("Waiting for {i}".format(i=t))
        t.join()
