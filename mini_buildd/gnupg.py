# -*- coding: utf-8 -*-
import os
import tempfile
import socket
import logging

from mini_buildd import globals, misc

log = logging.getLogger(__name__)

class GnuPG():
    def __init__(self, template):
        self.gpg_cmd = ["gpg",
                        "--homedir={h}".format(h=os.path.join(globals.HOME_DIR, ".gnupg")),
                        "--batch"]
        self.template = tempfile.TemporaryFile()
        self.template.write("""\
{t}
Name-Real: Mini Buildd Archive Key
Name-Email: mini-buildd@{h}
""".format(t=template, h=socket.getfqdn()))

    def prepare(self):
        if not self.get_pub_key():
            self.template.seek(0)
            misc.call(self.gpg_cmd + ["--gen-key"], stdin=self.template)

    def get_pub_key(self):
        return misc.call(self.gpg_cmd + ["--armor", "--export={i}".format(i="mini-buildd")])

    def get_fingerprint(self):
        return misc.call(self.gpg_cmd + ["--armor", "--fingerprint={i}".format(i="mini-buildd")])

if __name__ == "__main__":
    #misc.setup_test_logging()

    globals.HOME_DIR = "/tmp/gnupgtest"
    misc.mkdirs(globals.HOME_DIR)
    gnupg = GnuPG("""\
Key-Type: DSA
Key-Length: 1024
Expire-Date: 0""")
    gnupg.prepare()
    print gnupg.get_pub_key()
    print gnupg.get_fingerprint()
