# -*- coding: utf-8 -*-
"""
Run reprepro commands.
"""

import os, logging

from mini_buildd import misc, globals

log = logging.getLogger(__name__)

class Reprepro():
    def __init__(self, repository):
        self.repository = repository
        self._cmd = ["reprepro",  "--verbose", "--basedir={b}".format(b=self.repository.get_path())]

    def prepare(self):
        misc.mkdirs(os.path.join(self.repository.get_path(), "conf"))
        misc.mkdirs(self.repository.get_incoming_path())
        open(os.path.join(self.repository.get_path(), "conf", "distributions"), 'w').write(self.repository.repreproConfig())
        open(os.path.join(self.repository.get_path(), "conf", "incoming"), 'w').write("""\
Name: INCOMING
TempDir: /tmp
IncomingDir: {i}
Allow: {allow}
""".format(i=self.repository.get_incoming_path(), allow=" ".join(self.repository.uploadable_dists)))

        open(os.path.join(self.repository.get_path(), "conf", "options"), 'w').write("""\
gnupghome {h}
""".format(h=os.path.join(globals.HOME_DIR, ".gnupg")))

        # Update all indices (or create on initial install) via reprepro
        misc.call(self._cmd + ["clearvanished"])
        misc.call(self._cmd + ["export"])
        log.info("Prepared reprepro config: {d}".format(d=self.repository.get_path()))

    def processincoming(self):
        return misc.call(self._cmd + ["processincoming", "INCOMING"])
