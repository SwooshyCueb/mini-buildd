# -*- coding: utf-8 -*-
import StringIO
import os
import stat
import re
import datetime
import tempfile
import socket
import subprocess
import logging
import signal

import mini_buildd.globals
import mini_buildd.misc

log = logging.getLogger(__name__)

class GnuPG():
    def __init__(self, template):
        self.gpg_cmd = ["gpg",
                        "--homedir={h}".format(h=os.path.join(mini_buildd.globals.HOME_DIR, ".gnupg")),
                        "--batch"]
        self.template = template

    def prepare(self):
        if not self.get_pub_key():
            with tempfile.NamedTemporaryFile() as l:
                with tempfile.NamedTemporaryFile() as tpl:
                    tpl.write("""\
{t}
Name-Real: Mini Buildd Archive Key
Name-Email: mini-buildd@{h}
""".format(t=self.template, h=socket.getfqdn()))
                    tpl.seek(0)
                    try:
                        subprocess.check_call(self.gpg_cmd + ["--gen-key"],
                                              stdin=tpl,
                                              stdout=l, stderr=subprocess.STDOUT)
                    except:
                        l.seek(0)
                        log.error(l.read())
                        raise

    def purge(self):
        log.error(self.__name__ + ".purge(): STUB")

    def get_pub_key(self):
        result = ""
        with tempfile.NamedTemporaryFile() as stderr:
            with tempfile.NamedTemporaryFile() as stdout:
                try:
                    subprocess.check_call(self.gpg_cmd + ["--armor", "--export={i}".format(i="mini-buildd")],
                                          stdin=stderr,
                                          stdout=stdout)
                    stdout.seek(0)
                    return stdout.read()
                except:
                    stderr.seek(0)
                    log.error(stderr.read())
                    raise

if __name__ == "__main__":
    print __name__
    log.addHandler(logging.StreamHandler())

    mini_buildd.globals.HOME_DIR = "/tmp/gnupgtest"
    gnupg = GnuPG("""\
Key-Type: DSA
Key-Length: 1024
Expire-Date: 0""")
    gnupg.prepare()

    print gnupg.get_pub_key()
