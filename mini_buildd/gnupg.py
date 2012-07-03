# -*- coding: utf-8 -*-
import os, tempfile, shutil, socket, logging

from mini_buildd import setup, misc
from mini_buildd.models import msg_info

log = logging.getLogger(__name__)

class BaseGnuPG(object):
    def __init__(self, home):
        self.home = home
        self.gpg_cmd = ["gpg",
                        "--homedir={h}".format(h=home),
                        "--batch"]

    def get_pub_key(self, id):
        return misc.call(self.gpg_cmd + ["--armor", "--export={i}".format(i=id)])

    def get_fingerprint(self, id):
        return misc.call(self.gpg_cmd + ["--armor", "--fingerprint={i}".format(i=id)])

    def recv_key(self, keyserver, id):
        return misc.call(self.gpg_cmd + ["--armor", "--keyserver={ks}".format(ks=keyserver), "--recv-keys", id])

    def _purge_home(self):
        if os.path.exists(self.home):
            shutil.rmtree(self.home)

class GnuPG(BaseGnuPG):
    def __init__(self, template):
        super(GnuPG, self).__init__(home=os.path.join(setup.HOME_DIR, ".gnupg"))
        self.template = tempfile.TemporaryFile()
        self.template.write("""\
{t}
Name-Real: Mini Buildd Archive Key
Name-Email: mini-buildd@{h}
""".format(t=template, h=socket.getfqdn()))

    def prepare(self, r):
        if not self.get_pub_key():
            msg_info(r, "Generating GnuPG secret key (this might take some time)...")
            self.template.seek(0)
            misc.call(self.gpg_cmd + ["--gen-key"], stdin=self.template)
            msg_info(r, "New GnuPG secret key prepared...")
        else:
            msg_info(r, "GnuPG key already prepared...")

    def unprepare(self, r):
        self._purge_home()
        msg_info(r, "GnuPG setup removed: {h}".format(h=self.home))

    def get_pub_key(self):
        return super(GnuPG, self).get_pub_key("mini-buildd")

    def get_fingerprint(self):
        return super(GnuPG, self).get_fingerprint("mini-buildd")

class TmpGnuPG(BaseGnuPG):
    def __init__(self):
        super(TmpGnuPG, self).__init__(home=tempfile.mkdtemp())

    def __del__(self):
        self._purge_home()

if __name__ == "__main__":
    misc.setup_test_logging()

#    setup.HOME_DIR = "/tmp/gnupgtest"
#    misc.mkdirs(setup.HOME_DIR)
#    gnupg = GnuPG("""\
#Key-Type: DSA
#Key-Length: 1024
#Expire-Date: 0""")
#    gnupg.prepare()
#    print gnupg.get_pub_key()
#    print gnupg.get_fingerprint()

    gnupg = TmpGnuPG()
    gnupg.recv_key(keyserver="subkeys.pgp.net", id="473041FA")
    print gnupg.get_pub_key(id="473041FA")
    print gnupg.get_fingerprint(id="473041FA")
