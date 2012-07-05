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

    def gen_secret_key(self, template):
        with tempfile.TemporaryFile() as t:
            t.write(template)
            t.seek(0)
            misc.call(self.gpg_cmd + ["--gen-key"], stdin=t)

    def get_pub_key(self, id):
        return misc.call(self.gpg_cmd + ["--armor", "--export={i}".format(i=id)])

    def get_fingerprint(self, id):
        return misc.call(self.gpg_cmd + ["--armor", "--fingerprint={i}".format(i=id)])

    def recv_key(self, keyserver, id):
        return misc.call(self.gpg_cmd + ["--armor", "--keyserver={ks}".format(ks=keyserver), "--recv-keys", id])

    def add_pub_key(self, key):
        with tempfile.TemporaryFile() as t:
            t.write(key)
            t.seek(0)
            misc.call(self.gpg_cmd + ["--import"], stdin=t)

    def verify(self, signed_file, file=None):
        misc.call(self.gpg_cmd + ["--verify", signed_file] + [file] if file else [])

    def sign(self, file, id):
        signed_file = file + ".signed"
        misc.call(self.gpg_cmd + ["--armor", "--textmode", "--clearsign", "--local-user={i}".format(i=id), "--output={f}".format(f=signed_file), file])
        os.rename(signed_file, file)

class GnuPG(BaseGnuPG):
    def __init__(self, template):
        super(GnuPG, self).__init__(home=os.path.join(setup.HOME_DIR, ".gnupg"))
        self.template = """\
{t}
Name-Real: Mini Buildd Archive Key
Name-Email: mini-buildd@{h}
""".format(t=template, h=socket.getfqdn())

    def prepare(self, r):
        if not self.get_pub_key():
            msg_info(r, "Generating GnuPG secret key (this might take some time)...")
            self.gen_secret_key(self.template)
            msg_info(r, "New GnuPG secret key prepared...")
        else:
            msg_info(r, "GnuPG key already prepared...")

    def unprepare(self, r):
        if os.path.exists(self.home):
            shutil.rmtree(self.home)
            msg_info(r, "GnuPG setup removed: {h}".format(h=self.home))

    def get_pub_key(self):
        return super(GnuPG, self).get_pub_key("mini-buildd")

    def get_fingerprint(self):
        return super(GnuPG, self).get_fingerprint("mini-buildd")

class TmpGnuPG(BaseGnuPG):
    """
    >>> gnupg = TmpGnuPG()
    >>> gnupg.gen_secret_key("Key-Type: DSA\\nKey-Length: 1024\\nName-Email: test@key.org")
    >>> t = tempfile.NamedTemporaryFile()
    >>> t.write("A test file")
    >>> gnupg.sign(file=t.name, id="test@key.org")
    >>> gnupg.verify(t.name)
    >>> pub_key = gnupg.get_pub_key(id="test@key.org")
    >>> tgnupg = TmpGnuPG()
    >>> tgnupg.add_pub_key(pub_key)
    >>> tgnupg.verify(t.name)
    """
    def __init__(self):
        super(TmpGnuPG, self).__init__(home=tempfile.mkdtemp())

    def __del__(self):
        import shutil
        shutil.rmtree(self.home)

if __name__ == "__main__":
    misc.setup_test_logging()

    import doctest
    doctest.testmod()
