# -*- coding: utf-8 -*-
"""
Run reprepro commands.
"""

import os

import mini_buildd

class Reprepro():
    def __init__(self, repository):
        # Reprepro config
        path = repository.get_path()

        mini_buildd.misc.mkdirs(os.path.join(path, "conf"))
        mini_buildd.misc.mkdirs(os.path.join(path, "incoming"))
        open(os.path.join(path, "conf", "distributions"), 'w').write(repository.repreproConfig())
        open(os.path.join(path, "conf", "incoming"), 'w').write("""\
Name: INCOMING
TempDir: /tmp
IncomingDir: {i}
Allow: {allow}
""".format(i=os.path.join(path, "incoming"), allow=" ".join(repository.uploadable_dists)))

        open(os.path.join(path, "conf", "options"), 'w').write("""\
gnupghome {h}
""".format(h=os.path.join(path, ".gnupg")))

        # Update all indices (or create on initial install) via reprepro
        self._cmd = "reprepro --verbose --basedir='{b}' ".format(b=path)

        mini_buildd.misc.run_cmd("reprepro --verbose --basedir='{d}' clearvanished".format(d=path), False)
        mini_buildd.misc.run_cmd("reprepro --verbose --basedir='{d}' export".format(d=path), False)
        mini_buildd.log.info("Prepared reprepro config: {d}".format(d=path))

    def processincoming(self, cf=""):
        return mini_buildd.misc.run_cmd(self._cmd + "processincoming INCOMING \"{cf}\"".format(cf=os.path.basename(cf)), False)
