# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import shutil
import email.mime.text
import email.utils
import logging

import mini_buildd.misc

LOG = logging.getLogger(__name__)


class Package(mini_buildd.misc.API):
    __API__ = 1

# pylint: disable=R0801
    CHECKING = "CHECKING"
    REJECTED = "REJECTED"
    BUILDING = "BUILDING"
    FAILED = "FAILED"
    INSTALLED = "INSTALLED"
# pylint: enable=R0801

    def __init__(self, daemon, changes):
        super(Package, self).__init__()

        self._status = self.CHECKING
        self._status_desc = "."

        self.daemon = daemon
        self.changes = changes
        self.pid = changes.get_pkg_id()
        self.repository, self.distribution, self.suite = None, None, None
        self.requests, self.success, self.failed = {}, {}, {}

    def __unicode__(self):
        return "{s} ({d}): {p} ({f}/{r} arches built): {desc}".format(
            s=self._status,
            d=self.changes["Distribution"],
            p=self.pid,
            f=len(self.success),
            r=len(self.requests),
            desc=self._status_desc)

    def set_status(self, status, desc="."):
        self._status = status
        self._status_desc = desc

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
        ".. todo:: proper error handling, states."
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
        if self.failed:
            raise Exception("{p}: {n} mandatory architecture(s) failed".format(p=self.pid, n=len(self.failed)))
        self.repository.mbd_package_install(self)

    def archive(self):
        # Archive build results and request
        for _arch, c in self.success.items() + self.failed.items() + self.requests.items():
            c.archive()
        # Archive incoming changes
        self.changes.archive()
        # Purge complete package dir (if precheck failed, spool dir will not be present)
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
