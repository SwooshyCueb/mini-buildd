# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import time
import shutil
import codecs
import logging

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


if __name__ == "__main__":
    mini_buildd.misc.setup_console_logging()

    import mini_buildd.setup
    mini_buildd.setup.DEBUG.append("builder")

    GNUPG = mini_buildd.gnupg.TmpGnuPG()
    GNUPG.gen_secret_key("""Key-Type: DSA
Key-Length: 1024
Name-Real: Porter Test
Name-Email: test@porter""")

    K = KeyringPackage("test", GNUPG, "Porter Test", "test@porter")
