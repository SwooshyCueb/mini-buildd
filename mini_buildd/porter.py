# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import re
import time
import shutil
import subprocess
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

        mini_buildd.misc.call(["dpkg-source",
                               "-b",
                               "package"],
                              cwd=self.tmpdir,
                              env=self.environment)

        # Compute DSC file name
        self.dsc = os.path.join(self.tmpdir,
                                "{p}_{v}.dsc".format(p=self.package_name,
                                                     v=self.version))


class PortedPackage(mini_buildd.misc.TmpDir):
    def __init__(self, dsc_uri,
                 distribution, version_apdx, extra_cl_entries,
                 env, gnupg,
                 replace_version_apdx_regex=None):
        super(PortedPackage, self).__init__()

        mini_buildd.misc.call(["dget",
                               "--allow-unauthenticated",
                               "--download-only",
                               dsc_uri],
                              cwd=self.tmpdir,
                              env=env)

        dsc_file = os.path.basename(dsc_uri)
        dsc = debian.deb822.Dsc(file(os.path.join(self.tmpdir, dsc_file)))
        dst = "debian_source_tree"

        mini_buildd.misc.call(["dpkg-source",
                               "-x",
                               dsc_file,
                               dst],
                              cwd=self.tmpdir,
                              env=env)

        # Remove matching string from version if given; mainly
        # for internal automated backports so they don't get a
        # doubled version apdx like '~testSID+1~test60+1'
        if replace_version_apdx_regex:
            version = re.sub(replace_version_apdx_regex, version_apdx, dsc["Version"])
        else:
            version = dsc["Version"] + version_apdx

        dst_path = os.path.join(self.tmpdir, dst)
        mini_buildd.misc.call(["debchange",
                               "--newversion={v}".format(v=version),
                               "--force-distribution",
                               "--force-bad-version",
                               "--preserve",
                               "--dist={d}".format(d=distribution),
                               "Automated port via mini-buildd (no changes)."],
                              cwd=dst_path,
                              env=env)

        for entry in extra_cl_entries:
            mini_buildd.misc.call(["debchange",
                                   "--append",
                                   entry],
                                  cwd=dst_path,
                                  env=env)

        mini_buildd.misc.call(["dpkg-source", "-b", dst],
                              cwd=self.tmpdir,
                              env=env)

        self.changes = os.path.join(self.tmpdir,
                                    "{p}_{v}_source.changes".format(p=dsc["Source"],
                                                                    v=mini_buildd.misc.strip_epoch(version)))
        with open(self.changes, "w") as c:
            subprocess.check_call(["dpkg-genchanges",
                                   "-S",
                                   "-sa"],
                                  cwd=dst_path,
                                  env=env,
                                  stdout=c)

        gnupg.sign(self.changes)

    def upload(self, hopo):
        mini_buildd.changes.Changes(self.changes).upload(hopo)
        LOG.info("Ported package uploaded: {c}".format(c=self.changes))


if __name__ == "__main__":
    mini_buildd.misc.setup_console_logging()

    import contextlib
    import mini_buildd.setup
    mini_buildd.setup.DEBUG.append("builder")

    GNUPG = mini_buildd.gnupg.TmpGnuPG()
    GNUPG.gen_secret_key("""Key-Type: DSA
Key-Length: 1024
Name-Real: Porter Test
Name-Email: test@porter""")

    K = KeyringPackage("test", GNUPG, "Porter Test", "test@porter")

    with contextlib.closing(PortedPackage("file://" + K.dsc,
                                          "squeeze-test-unstable", "~test60+1", ["MINI_BUILDD: BACKPORT-MODE"],
                                          K.environment, GNUPG)) as P:
        P.upload(mini_buildd.misc.HoPo("localhost:8067"))
