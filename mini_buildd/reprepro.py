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
        self.repository = repository
        self._cmd = "reprepro --verbose --basedir='{b}' ".format(b=self.repository.get_path())

    def prepare(self):
        mini_buildd.misc.mkdirs(os.path.join(self.repository.get_path(), "conf"))
        mini_buildd.misc.mkdirs(self.repository.get_incoming_path())
        open(os.path.join(self.repository.get_path(), "conf", "distributions"), 'w').write(self.repository.repreproConfig())
        open(os.path.join(self.repository.get_path(), "conf", "incoming"), 'w').write("""\
Name: INCOMING
TempDir: /tmp
IncomingDir: {i}
Allow: {allow}
""".format(i=self.repository.get_incoming_path(), allow=" ".join(self.repository.uploadable_dists)))

        open(os.path.join(self.repository.get_path(), "conf", "options"), 'w').write("""\
gnupghome {h}
""".format(h=os.path.join(self.repository.get_path(), ".gnupg")))

        # Update all indices (or create on initial install) via reprepro
        mini_buildd.misc.run_cmd(self._cmd + "clearvanished")
        mini_buildd.misc.run_cmd(self._cmd + "export")
        log.info("Prepared reprepro config: {d}".format(d=self.repository.get_path()))

    def processincoming(self):
        return mini_buildd.misc.run_cmd(self._cmd + "processincoming INCOMING")
