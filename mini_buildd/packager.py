# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import shutil
import email.mime.text
import email.utils
import logging

LOG = logging.getLogger(__name__)


class Package(object):
    DONE = 0
    INCOMPLETE = 1

    def __init__(self, daemon, changes, repository, dist, suite):
        self.done = False
        self.daemon = daemon
        self.changes = changes
        self.repository, self.distribution, self.suite = repository, dist, suite
        self.pid = changes.get_pkg_id()

        self.repository.mbd_package_precheck(self)

        self.requests = self.changes.gen_buildrequests(daemon, self.repository, self.distribution)
        self.success = {}
        self.failed = {}
        for _key, breq in self.requests.items():
            breq.upload_buildrequest(daemon.mbd_get_http_hopo())

    def __unicode__(self):
        return u"{s} ({d}): {p} ({f}/{r} arches built)".format(
            s="BUILDING" if not self.done else "FAILED" if self.failed else "BUILD",
            d=self.changes["Distribution"],
            p=self.pid,
            f=len(self.success),
            r=len(self.requests))

    def notify(self):
        results = u""
        for arch, bres in self.failed.items() + self.success.items():
            results += u"{s}({a}): {b}\n".format(
                s=bres["Sbuild-Status"],
                a=arch,
                b=self.daemon.mbd_get_http_url() + "/log/" + bres.archive_dir + "/" + bres.buildlog_name)

        results += u"\n"
        body = email.mime.text.MIMEText(results + self.changes.dump(), _charset="UTF-8")

        self.daemon.mbd_notify(
            unicode(self),
            body,
            self.repository,
            self.changes)

    def update(self, bres):
        arch = bres["Architecture"]
        status = bres["Sbuild-Status"]
        retval = int(bres["Sbuildretval"])
        LOG.info("{p}: Got build result for '{a}': {r} ({s})".format(p=self.pid, a=arch, r=retval, s=status))

        if retval == 0:
            self.success[arch] = bres
        else:
            self.failed[arch] = bres

        missing = len(self.requests) - len(self.success) - len(self.failed)
        if missing > 0:
            LOG.debug("{p}: {n} arches still missing.".format(p=self.pid, n=missing))
            return self.INCOMPLETE

        # Finish up
        self.done = True
        LOG.info("{p}: All build results received".format(p=self.pid))
        try:
            if self.failed:
                raise Exception("{p}: {n} mandatory architecture(s) failed".format(p=self.pid, n=len(self.failed)))

            self.repository.mbd_package_install(self)

        except Exception as e:
            LOG.error(u"{e}".format(e=e))
            # todo Error!
        finally:
            # Archive build results and request
            for arch, c in self.success.items() + self.failed.items() + self.requests.items():
                c.archive()
            # Archive incoming changes
            self.changes.archive()
            # Purge complete package dir
            shutil.rmtree(self.changes.get_spool_dir())

            self.notify()

        return self.DONE
