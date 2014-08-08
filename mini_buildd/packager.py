# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import shutil
import datetime
import logging

import mini_buildd.misc

LOG = logging.getLogger(__name__)


class Package(mini_buildd.misc.Status):
    FAILED = -2
    REJECTED = -1
    CHECKING = 0
    BUILDING = 1
    INSTALLING = 2
    INSTALLED = 10

    def __init__(self, daemon, changes):
        super(Package, self).__init__(
            stati={self.FAILED: "FAILED",
                   self.REJECTED: "REJECTED",
                   self.CHECKING: "CHECKING",
                   self.BUILDING: "BUILDING",
                   self.INSTALLING: "INSTALLING",
                   self.INSTALLED: "INSTALLED"})

        self.started = datetime.datetime.now()
        self.finished = None

        self.daemon = daemon
        self.changes = changes
        self.pid = changes.get_pkg_id()
        self.repository, self.distribution, self.suite, self.distribution_string = None, None, None, None
        self.requests, self.success, self.failed = {}, {}, {}
        self.port_report = {}

    def __unicode__(self):
        def arch_status():
            result = []
            for key, _r in self.requests.items():
                p = ""
                if key in self.success:
                    p = "+"
                elif key in self.failed:
                    p = "-"
                result.append("{p}{a}".format(p=p, a=key))
            return result

        return mini_buildd.misc.pkg_fmt(self.status,
                                        self.distribution_string,
                                        self.changes["Source"],
                                        self.changes["Version"],
                                        extra=" ".join(arch_status()),
                                        message=self.status_desc)

    @property
    def took(self):
        return round(mini_buildd.misc.timedelta_total_seconds(self.finished - self.started), 1) if self.finished else "n/a"

    def precheck(self):
        # Get/check repository, distribution and suite for changes
        self.repository, self.distribution, self.suite, rollback = self.daemon.parse_distribution(self.changes["Distribution"])
        # Actual full distribution string; A shortcut for
        # 'self.changes["Distribution"]', but may also differ if there's a meta distribution like unstable in changes.
        self.distribution_string = self.suite.mbd_get_distribution_string(self.repository, self.distribution)

        if rollback is not None:
            raise Exception("Rollback distribution are not uploadable")

        if not self.suite.uploadable:
            raise Exception("Suite '{s}' is not uploadable".format(s=self.suite))

        if not self.repository.mbd_is_active():
            raise Exception("Repository '{r}' is not active".format(r=self.repository))

        # Authenticate
        if self.repository.allow_unauthenticated_uploads:
            LOG.warn("Unauthenticated uploads allowed. Using '{c}' unchecked".format(c=self.changes.file_name))
        else:
            self.daemon.keyrings.get_uploaders()[self.repository.identity].verify(self.changes.file_path)

        # Repository package prechecks
        self.repository.mbd_package_precheck(self.distribution, self.suite, self.changes["Source"], self.changes["Version"])

        # Generate build requests
        self.requests = self.changes.gen_buildrequests(self.daemon.model, self.repository, self.distribution, self.suite)

        # Upload buildrequests
        for _key, breq in self.requests.items():
            try:
                breq.upload_buildrequest(self.daemon.model.mbd_get_http_hopo())
            except Exception as e:
                mini_buildd.setup.log_exception(LOG,
                                                "{i}: Buildrequest upload failed".format(i=breq.get_pkg_id()),
                                                e)
                # Upload failure build result to ourselves
                breq.upload_failed_buildresult(self.daemon.model.mbd_gnupg, self.daemon.model.mbd_get_ftp_hopo(), 100, "upload-failed", e)

    def add_buildresult(self, bres):
        self.daemon.keyrings.get_remotes().verify(bres.file_path)

        arch = bres["Architecture"]

        # Retval and status must be the same with sbuild in mode user, so status is not really needed
        # status may also be none in case some non-sbuild build error occurred
        retval = int(bres["Sbuildretval"])
        status = bres.get("Sbuild-Status")
        lintian = bres.get("Sbuild-Lintian")

        LOG.info("{p}: Got build result for '{a}': {r}={s}, lintian={l}".format(p=self.pid, a=arch, r=retval, s=status, l=lintian))

        def check_lintian():
            return lintian == "pass" or \
                self.suite.experimental or \
                self.distribution.lintian_mode < self.distribution.LINTIAN_FAIL_ON_ERROR or \
                self.changes.magic_backport_mode

        if retval == 0 and (status == "skipped" or check_lintian()):
            self.success[arch] = bres
        else:
            self.failed[arch] = bres

        missing = len(self.requests) - len(self.success) - len(self.failed)
        if missing <= 0:
            self.finished = datetime.datetime.now()

    def install(self):
        """
        Install package to repository.

        This may throw on error, and if so, no changes should be
        done to the repo.
        """

        # Install to reprepro repository
        self.repository.mbd_package_install(self.distribution, self.suite, self.changes, self.success)

        # Installed. Finally, try to serve magic auto backports
        for to_dist_str in self.changes.magic_auto_backports:
            try:
                self.daemon.port(self.changes["Source"],
                                 self.distribution_string,
                                 to_dist_str,
                                 self.changes["Version"])
                self.port_report[to_dist_str] = "Requested"
            except Exception as e:
                self.port_report[to_dist_str] = "FAILED: {e}".format(e=e)
                mini_buildd.setup.log_exception(LOG, "{i}: Automatic package port failed for: {d}".format(i=self.changes.get_pkg_id(), d=to_dist_str), e)

    def move_to_pkglog(self):
        # Archive build results and request
        for _arch, c in self.success.items() + self.failed.items() + self.requests.items():
            c.move_to_pkglog(self.get_status() == self.INSTALLED)
        # Archive incoming changes
        self.changes.move_to_pkglog(self.get_status() == self.INSTALLED)

        # Purge complete package spool dir (if precheck failed, spool dir will not be present, so we need to ignore errors here)
        mini_buildd.misc.skip_if_keep_in_debug(shutil.rmtree, self.changes.get_spool_dir(), ignore_errors=True)

        # Hack: In case the changes comes from a temporary directory (ports!), we take care of purging that tmpdir here
        tmpdir = mini_buildd.misc.TmpDir.file_dir(self.changes.file_path)
        if tmpdir:
            mini_buildd.misc.TmpDir(tmpdir).close()

        # On installed: In case there is a "failed" log of the same version, remove it.
        if self.get_status() == self.INSTALLED:
            # The pkglog_dir must be non-None on INSTALLED status
            failed_logdir = os.path.dirname(self.changes.get_pkglog_dir(installed=False, relative=False))
            LOG.debug("Purging failed log dir: {f}".format(f=failed_logdir))
            shutil.rmtree(failed_logdir, ignore_errors=True)

    def notify(self):
        def header(title, underline="-"):
            return "{t}\n{u}\n".format(t=title, u=underline * len(title))

        def bres_result(arch, bres):
            return "{a} ({s}): {b}\n".format(
                a=arch,
                s=bres.bres_stat,
                b=os.path.join(self.daemon.model.mbd_get_http_url(),
                               "log",
                               unicode(bres.get_pkglog_dir(self.get_status() == self.INSTALLED)),
                               bres.buildlog_name))

        results = header(self.__unicode__(), "=")
        results += "\n"

        if self.failed:
            results += header("Failed builds")
            for arch, bres in self.failed.items():
                results += bres_result(arch, bres)
            results += "\n"

        if self.success:
            results += header("Successful builds")
            for arch, bres in self.success.items():
                results += bres_result(arch, bres)
            results += "\n"

        results += header("Changes")
        results += self.changes.dump()

        if self.port_report:
            results += "\n"
            results += header("Port Report")
            results += "\n".join(("{d:<25}: {r}".format(d=d, r=r) for d, r in self.port_report.items()))

        self.daemon.model.mbd_notify(
            self.__unicode__(),
            results,
            self.repository,
            self.changes)


class LastPackage(mini_buildd.misc.API):
    """
    Subset of 'Package' for pickled statistics.
    """
    __API__ = -99

    def __init__(self, package):
        super(LastPackage, self).__init__()

        self.identity = package.__unicode__()

        self.started = package.started
        self.took = package.took
        self.log = os.path.join("/mini_buildd/log", os.path.dirname(unicode(package.changes.get_pkglog_dir(installed=True))))

        self.changes = {}
        for k in ["source", "distribution", "version"]:
            self.changes[k] = package.changes[k]

        self.status = package.status
        self.status_desc = package.status_desc

        self.requests = {}
        for a, r in package.requests.items():
            self.requests[a] = {"remote_http_url": r.remote_http_url}

        def cp_bres(src, dst):
            for a, r in src.items():
                dst[a] = {"remote_http_url": r.remote_http_url,
                          "bres_stat": r.bres_stat,
                          "log": os.path.join("/log", unicode(r.get_pkglog_dir(package.get_status() == package.INSTALLED)), r.buildlog_name)}

        self.success = {}
        cp_bres(package.success, self.success)

        self.failed = {}
        cp_bres(package.failed, self.failed)

    def __unicode__(self):
        return self.identity


def package_close(daemon, package):
    """
    Close package. Just continue on errors, but log them; guarantee to remove it from the packages dict.
    """
    try:
        package.move_to_pkglog()
        package.notify()
        daemon.last_packages.appendleft(LastPackage(package))
    except Exception as e:
        mini_buildd.setup.log_exception(LOG, "Error closing package '{p}'".format(p=package.pid), e, level=logging.CRITICAL)
    finally:
        del daemon.packages[package.pid]


def run(daemon, changes):
    pid = changes.get_pkg_id()

    if changes.type == changes.TYPE_BRES:
        if pid not in daemon.packages:
            raise Exception("{p}: Stray build result (not building here).".format(p=pid))

        package = daemon.packages[pid]

        try:
            package.add_buildresult(changes)
            if package.finished:
                package.install()
                package.set_status(package.INSTALLED)
                package_close(daemon, package)
        except Exception as e:
            package.set_status(package.FAILED, unicode(e))
            package_close(daemon, package)
            mini_buildd.setup.log_exception(LOG, "Package '{p}' FAILED".format(p=pid), e)

    else:  # User upload
        if pid in daemon.packages:
            raise Exception("Internal error: Uploaded package already in packages list.")

        package = mini_buildd.packager.Package(daemon, changes)
        daemon.packages[pid] = package
        try:
            package.precheck()
            package.set_status(package.BUILDING)
        except Exception as e:
            package.set_status(package.REJECTED, unicode(e))
            package_close(daemon, package)
            mini_buildd.setup.log_exception(LOG, "Package '{p}' REJECTED".format(p=pid), e)
