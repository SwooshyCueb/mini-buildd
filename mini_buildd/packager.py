# -*- coding: utf-8 -*-
import os
import shutil
import re
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
        self.repository, self.dist, self.suite = repository, dist, suite
        self.pid = changes.get_pkg_id()
        self.requests = self.changes.gen_buildrequests(daemon, self.repository, self.dist)
        self.success = {}
        self.failed = {}
        for _key, breq in self.requests.items():
            breq.upload_buildrequest(daemon.mbd_get_http_hopo())

    def __unicode__(self):
        return u"{s} ({d}): {p} ({f}/{r} arches)".format(
            s="BUILDING" if not self.done else "FAILED" if self.failed else "BUILD",
            d=self.changes["Distribution"],
            p=self.pid,
            f=len(self.success),
            r=len(self.requests))

    def notify(self):
        results = u""
        for arch, c in self.failed.items() + self.success.items():
            for fd in c.get_files():
                f = fd["name"]
                if re.compile("^.*\.buildlog$").match(f):
                    results += u"{s}({a}): {b}\n".format(s=c["Sbuild-Status"], a=arch, b=self.daemon.mbd_get_http_url() + "/" +
                                                         os.path.join(u"log", c["Distribution"], c["Source"], c["Version"], arch, f))

        results += u"\n"
        body = email.mime.text.MIMEText(results + self.changes.dump(), _charset="UTF-8")

        self.daemon.mbd_notify(
            unicode(self),
            body,
            self.repository,
            self.changes)

    def update(self, result):
        arch = result["Architecture"]
        status = result["Sbuild-Status"]
        retval = int(result["Sbuildretval"])
        LOG.info("{p}: Got build result for '{a}': {r} ({s})".format(p=self.pid, a=arch, r=retval, s=status))

        if retval == 0:
            self.success[arch] = result
        else:
            self.failed[arch] = result

        missing = len(self.requests) - len(self.success) - len(self.failed)
        if missing > 0:
            LOG.debug("{p}: {n} arches still missing.".format(p=self.pid, n=missing))
            return self.INCOMPLETE

        # Finish up
        LOG.info("{p}: All build results received".format(p=self.pid))
        try:
            if self.failed:
                raise Exception("{p}: {n} mandatory architecture(s) failed".format(p=self.pid, n=len(self.failed)))

            for arch, c in self.success.items():
                self.repository.mbd_install_buildresult(c, self.dist, self.suite)

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

        self.done = True
        return self.DONE
