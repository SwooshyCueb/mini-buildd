# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import shutil
import email.mime.text
import email.utils
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

        self.daemon = daemon
        self.changes = changes
        self.pid = changes.get_pkg_id()
        self.repository, self.distribution, self.suite = None, None, None
        self.requests, self.success, self.failed = {}, {}, {}

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

        return "{s}: {p} ({d}): {a}: {desc}".format(
            s=self.status,
            p=self.pid,
            d=self.changes["Distribution"],
            a=" ".join(arch_status()),
            desc=self.status_desc)

    def precheck(self, uploader_keyrings):
        # Get/check repository, distribution and suite for changes
        self.repository, self.distribution, self.suite, rollback = self.daemon.parse_distribution(self.changes["Distribution"])

        if rollback is not None:
            raise Exception("Rollback distribution are not uploadable")

        if not self.suite.uploadable:
            raise Exception("Suite '{s}' is not uploadable".format(s=self.suite))

        if not self.repository.mbd_is_active():
            raise Exception("Repository '{r}' is not active".format(r=self.repository))

        self.repository.mbd_check_version(self.changes["Version"], self.distribution, self.suite)

        # Authenticate
        if self.repository.allow_unauthenticated_uploads:
            LOG.warn("Unauthenticated uploads allowed. Using '{c}' unchecked".format(c=self.changes.file_name))
        else:
            uploader_keyrings[self.repository.identity].verify(self.changes.file_path)

        # Check if this version is already in repository
        if self.repository.mbd_package_find(self.changes["Source"], version=self.changes["Version"]):
            raise Exception("Version '{v}' already installed".format(v=self.changes["Version"]))

        # Generate build requests
        self.requests = self.changes.gen_buildrequests(self.daemon.model, self.repository, self.distribution, self.suite)

        # Upload buildrequests
        for _key, breq in self.requests.items():
            try:
                breq.upload_buildrequest(self.daemon.model.mbd_get_http_hopo())
            except Exception as e:
                mini_buildd.setup.log_exception(LOG,
                                                "{i}: Buildrequest upload to {h} failed".format(i=breq.get_pkg_id(),
                                                                                                h=self.daemon.model.mbd_get_ftp_hopo()),
                                                e)
                # Upload failure build result to ourselves
                breq.upload_failed_buildresult(self.daemon.model.mbd_gnupg, self.daemon.model.mbd_get_ftp_hopo(), 100, "upload-failed", e)

    def add_buildresult(self, bres, remotes_keyring):
        remotes_keyring.verify(bres.file_path)

        arch = bres["Architecture"]

        # Retval and status must be the same with sbuild in mode user, so status is not really needed
        # status may also be none in case some non-sbuild build error occured
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
        return missing <= 0

    def install(self):
        """
        Install package to repository.

        This may throw on error, and if so, no changes should be
        done to the repo.
        """

        # Install to reprepro repository
        self.repository.mbd_package_install(self.distribution, self.suite, self.success)

        # Installed. Finally, try to serve magic auto backports
        dsc_url = "file://" + os.path.join(os.path.dirname(self.changes.file_path), self.changes.dsc_name)
        for dist in self.changes.magic_auto_backports:
            try:
                self.daemon.port(dsc_url, dist,
                                 self.repository.layout.mbd_get_mandatory_version_regex(self.repository, self.distribution, self.suite))
            except Exception as e:
                mini_buildd.setup.log_exception(LOG, "{i}: Automatic package port failed for: {d}".format(i=self.changes.get_pkg_id(), d=dist), e)

    def archive(self):
        # Archive build results and request
        for _arch, c in self.success.items() + self.failed.items() + self.requests.items():
            c.archive(self.get_status() == self.INSTALLED)
        # Archive incoming changes
        self.changes.archive(self.get_status() == self.INSTALLED)
        # Purge complete package dir (if precheck failed, spool dir will not be present, so we need to ignore errors here)
        shutil.rmtree(self.changes.get_spool_dir(), ignore_errors=True)

        # In case the changes comes from a temporary directory (ports!), we take care of purging that tmpdir here
        tmpdir = mini_buildd.misc.TmpDir.file_dir(self.changes.file_path)
        if tmpdir:
            LOG.debug("Purging port tmpdir: {t}".format(t=tmpdir))
            shutil.rmtree(tmpdir, ignore_errors=True)

    def notify(self):
        def header(title, underline="-"):
            return "{t}:\n{u}\n".format(t=title, u=underline * (1 + len(title)))

        def bres_result(arch, bres):
            return "{a} ({s}): {b}\n".format(
                a=arch,
                s=bres.bres_stat,
                b=self.daemon.model.mbd_get_http_url() + "/log/" + bres.get_archive_dir(self.get_status() == self.INSTALLED) + "/" + bres.buildlog_name)

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

        body = email.mime.text.MIMEText(results, _charset="UTF-8")

        self.daemon.model.mbd_notify(
            self.__unicode__(),
            body,
            self.repository,
            self.changes)


class LastPackage(mini_buildd.misc.API):
    __API__ = -100

    def __init__(self, package):
        super(LastPackage, self).__init__()

        self.package = package.changes["Source"]
        self.identity = package.__unicode__()

        self.success = {}
        for arch, bres in package.success.items():
            self.success[arch] = {
                "log": os.path.join(bres.get_archive_dir(package.get_status() == package.INSTALLED), bres.buildlog_name),
                "stat": bres.bres_stat}

        self.failed = {}
        for arch, bres in package.failed.items():
            self.failed[arch] = {
                "log": os.path.join(bres.get_archive_dir(package.get_status() == package.INSTALLED), bres.buildlog_name),
                "stat": bres.bres_stat}

    def __unicode__(self):
        return self.identity


def run(daemon, changes, packages, last_packages, remotes_keyring, uploader_keyrings):
    if changes.is_buildresult():
        if not changes.get_pkg_id() in packages:
            raise Exception("No active package for that build result.")

        package = packages[changes.get_pkg_id()]

        try:
            if package.add_buildresult(changes, remotes_keyring):
                package.install()
                package.set_status(package.INSTALLED)
                package.archive()
                package.notify()
                del packages[changes.get_pkg_id()]
                last_packages.appendleft(mini_buildd.packager.LastPackage(package))
        except Exception as e:
            package.set_status(package.FAILED, unicode(e))
            package.archive()
            package.notify()
            del packages[changes.get_pkg_id()]
            last_packages.appendleft(mini_buildd.packager.LastPackage(package))

            mini_buildd.setup.log_exception(LOG, "Package FAILED", e)

    else:  # User upload
        if changes.get_pkg_id() in packages:
            raise Exception("Internal error: Uploaded package already in packages list.")

        package = mini_buildd.packager.Package(daemon, changes)
        packages[changes.get_pkg_id()] = package
        try:
            package.precheck(uploader_keyrings)
            package.set_status(package.BUILDING)
        except Exception as e:
            package.set_status(package.REJECTED, unicode(e))
            package.archive()
            package.notify()
            del packages[changes.get_pkg_id()]
            last_packages.appendleft(mini_buildd.packager.LastPackage(package))

            mini_buildd.setup.log_exception(LOG, "Package REJECTED", e)
