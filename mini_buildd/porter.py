# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import glob
import re
import time
import shutil
import codecs
import logging

import debian.deb822

import mini_buildd.misc
import mini_buildd.changes

LOG = logging.getLogger(__name__)


class KeyringPackage(mini_buildd.misc.TmpDir):
    def __init__(self, identity, gpg, debfullname, debemail, tpl_dir="/usr/share/doc/mini-buildd/examples/packages/archive-keyring-template"):
        super(KeyringPackage, self).__init__()

        self.package_name = "{i}-archive-keyring".format(i=identity)
        self.environment = mini_buildd.misc.taint_env(
            {"DEBEMAIL": debemail,
             "DEBFULLNAME": debfullname,
             "GNUPGHOME": gpg.home})
        self.version = time.strftime("%Y%m%d%H%M%S", time.gmtime())

        # Copy template, and replace %ID% and %MAINT% in all files
        p = os.path.join(self.tmpdir, "package")
        shutil.copytree(tpl_dir, p)
        for root, _dirs, files in os.walk(p):
            for f in files:
                old_file = os.path.join(root, f)
                new_file = old_file + ".new"
                codecs.open(new_file, "w", encoding="UTF-8").write(
                    mini_buildd.misc.subst_placeholders(
                        codecs.open(old_file, "r", encoding="UTF-8").read(),
                        {"ID": identity,
                         "MAINT": "{n} <{e}>".format(n=debfullname, e=debemail)}))
                os.rename(new_file, old_file)

        # Export public GnuPG key into the package
        gpg.export(os.path.join(p, self.package_name + ".gpg"))

        # Generate changelog entry
        mini_buildd.misc.call(["debchange",
                               "--create",
                               "--package={p}".format(p=self.package_name),
                               "--newversion={v}".format(v=self.version),
                               "[mini-buildd] Automatic keyring package template for {i}.".format(i=identity)],
                              cwd=p,
                              env=self.environment)
        mini_buildd.misc.call(["dpkg-buildpackage", "-S", "-sa"],
                              cwd=p,
                              env=self.environment)

        # Compute DSC file name
        dscs = glob.glob(os.path.join(self.tmpdir, "*.dsc"))
        if len(dscs) != 1:
            raise Exception("Expected exactly one dsc after building, got {l}.".format(l=len(dscs)))
        self.dsc = dscs[0]


class PortedPackage(mini_buildd.misc.TmpDir):
    def __init__(self, dsc_uri,
                 distribution, version_apdx, extra_cl_entries,
                 env,
                 replace_version_apdx_regex=None):
        super(PortedPackage, self).__init__()

        mini_buildd.misc.call(["dget", "--allow-unauthenticated", "--extract", dsc_uri], cwd=self.tmpdir, env=env)
        dirs = [d for d in os.listdir(self.tmpdir) if os.path.isdir(os.path.join(self.tmpdir, d))]
        if len(dirs) != 1:
            raise Exception("Expected exactly one dir after unpacking dsc, got {l}.".format(l=len(dirs)))
        d = dirs[0]
        p = os.path.join(self.tmpdir, d)

        dsc = debian.deb822.Dsc(file(os.path.join(self.tmpdir, os.path.basename(dsc_uri))))

        # Remove matching string from version if given; mainly
        # for internal automated backports so they don't get a
        # doubled version apdx like '~testSID+1~test60+1'
        if replace_version_apdx_regex:
            version = re.sub(replace_version_apdx_regex, version_apdx, dsc["Version"])
        else:
            version = dsc["Version"] + version_apdx

        mini_buildd.misc.call(["debchange",
                               "--newversion={v}".format(v=version),
                               "--force-distribution",
                               "--force-bad-version",
                               "--preserve",
                               "--dist={d}".format(d=distribution),
                               "Automated port via mini-buildd (no changes)."],
                              cwd=p,
                              env=env)

        for entry in extra_cl_entries:
            mini_buildd.misc.call(["debchange",
                                   "--append",
                                   entry],
                                  cwd=p,
                                  env=env)

        mini_buildd.misc.call(["dpkg-buildpackage", "-S", "-sa", "-d"],
                              cwd=p,
                              env=env)

    def upload(self, hopo):
        for c in glob.glob(os.path.join(self.tmpdir, "*.changes")):
            mini_buildd.changes.Changes(c).upload(hopo)
            LOG.info("Ported package uploaded: {c}".format(c=c))


if __name__ == "__main__":
    mini_buildd.misc.setup_test_logging()

    import contextlib
    GNUPG = mini_buildd.gnupg.TmpGnuPG()
    GNUPG.gen_secret_key("""Key-Type: DSA
Key-Length: 1024
Name-Real: Porter Test
Name-Email: test@porter""")

    K = KeyringPackage("test", GNUPG, "Porter Test", "test@porter")

    with contextlib.closing(PortedPackage("file://" + K.dsc,
                                          "squeeze-test-unstable", "~test60+1", ["MINI_BUILDD: BACKPORT-MODE"],
                                          K.environment)) as P:
        P.upload(mini_buildd.misc.HoPo("localhost:8067"))
