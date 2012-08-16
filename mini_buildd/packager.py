# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import shutil
import email.mime.text
import email.utils
import logging

import mini_buildd.misc

LOG = logging.getLogger(__name__)


class Package(mini_buildd.misc.APIStatus):
    __API__ = -1

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

        return "{p} ({d}): {s} ({a}).".format(
            p=self.pid,
            d=self.changes["Distribution"],
            s=self.status,
            a=" ".join(arch_status()))

    def precheck(self, uploader_keyrings):
        # Get/check repository, distribution and suite for changes
        self.repository, self.distribution, self.suite = self.changes.get_repository()

        # Authenticate
        if self.repository.allow_unauthenticated_uploads:
            LOG.warn("Unauthenticated uploads allowed. Using '{c}' unchecked".format(c=self.changes.file_name))
        else:
            uploader_keyrings[self.repository.identity].verify(self.changes.file_path)

        # Check if this version is already in repository
        if self.changes["Version"] in self.repository.mbd_package_search(None, self.changes["Source"], fmt=self.repository.MBD_SEARCH_FMT_VERSIONS):
            raise Exception("Version already in repository")

        # Generate build requests
        self.requests = self.changes.gen_buildrequests(self.daemon, self.repository, self.distribution)

        # Upload buildrequests
        for _key, breq in self.requests.items():
            breq.upload_buildrequest(self.daemon.mbd_get_http_hopo())

    def add_buildresult(self, bres, remotes_keyring):
        """
        .. todo:: Better inspect bres fail status: lintian, rejected, etc...
        """
        remotes_keyring.verify(bres.file_path)

        arch = bres["Architecture"]
        status = bres["Sbuild-Status"]
        retval = int(bres["Sbuildretval"])
        LOG.info("{p}: Got build result for '{a}': {r} ({s})".format(p=self.pid, a=arch, r=retval, s=status))

        if retval == 0:
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
        archall = [a.architecture.name for a in self.distribution.architectureoption_set.all() if a.build_architecture_all]
        archman = [a.architecture.name for a in self.distribution.architectureoption_set.all() if not a.optional]
        LOG.debug("Found archall={a}".format(a=archall))
        LOG.debug("Found archman={a}".format(a=archman))

        mandatory_fails = [arch for arch in self.failed.keys() if arch in archman]
        if mandatory_fails:
            raise Exception("{n} mandatory architecture(s) failed: {a}".format(n=len(mandatory_fails), a=" ".join(mandatory_fails)))

        # First, install the archall arch, so we fail early in case there are problems with the uploaded dsc.
        for bres in [s for a, s in self.success.items() if a in archall]:
            self.repository.mbd_package_install(bres)

        # Second, install all other archs
        for bres in [s for a, s in self.success.items() if not a in archall]:
            self.repository.mbd_package_install(bres)

    def archive(self):
        # Archive build results and request
        for _arch, c in self.success.items() + self.failed.items() + self.requests.items():
            c.archive()
        # Archive incoming changes
        self.changes.archive()
        # Purge complete package dir (if precheck failed, spool dir will not be present, so we need to ignore errors here)
        shutil.rmtree(self.changes.get_spool_dir(), ignore_errors=True)

    def notify(self):
        results = ""
        for arch, bres in self.failed.items() + self.success.items():
            results += "{s}({a}): {b}\n".format(
                s=bres["Sbuild-Status"],
                a=arch,
                b=self.daemon.mbd_get_http_url() + "/log/" + bres.archive_dir + "/" + bres.buildlog_name)

        results += "\n"
        body = email.mime.text.MIMEText(results + self.changes.dump(), _charset="UTF-8")

        self.daemon.mbd_notify(
            self.__unicode__(),
            body,
            self.repository,
            self.changes)
