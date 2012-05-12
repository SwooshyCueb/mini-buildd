# -*- coding: utf-8 -*-
"""
Run reprepro commands.
"""

import os
import logging

import mini_buildd

log = logging.getLogger(__name__)

class Reprepro():
    def __init__(self, repository):
        # Reprepro config
        path = repository.get_path()

        mini_buildd.misc.mkdirs(os.path.join(path, "conf"))
        mini_buildd.misc.mkdirs(repository.get_incoming_path())
        open(os.path.join(path, "conf", "distributions"), 'w').write(repository.repreproConfig())
        open(os.path.join(path, "conf", "incoming"), 'w').write("""\
Name: INCOMING
TempDir: /tmp
IncomingDir: {i}
Allow: {allow}
""".format(i=repository.get_incoming_path(), allow=" ".join(repository.uploadable_dists)))

        open(os.path.join(path, "conf", "options"), 'w').write("""\
gnupghome {h}
""".format(h=os.path.join(path, ".gnupg")))

        # Update all indices (or create on initial install) via reprepro
        self._cmd = "reprepro --verbose --basedir='{b}' ".format(b=path)

        mini_buildd.misc.run_cmd("reprepro --verbose --basedir='{d}' clearvanished".format(d=path))
        mini_buildd.misc.run_cmd("reprepro --verbose --basedir='{d}' export".format(d=path))
        log.info("Prepared reprepro config: {d}".format(d=path))

    def processincoming(self):
        return mini_buildd.misc.run_cmd(self._cmd + "processincoming INCOMING")
