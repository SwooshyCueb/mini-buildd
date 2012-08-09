# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import tempfile
import shutil
import subprocess
import logging

import mini_buildd.misc
import mini_buildd.setup

LOG = logging.getLogger(__name__)


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
            mini_buildd.misc.call(self.gpg_cmd + ["--gen-key"], stdin=t)

    def export(self, dest_file):
        with open(dest_file, "w") as f:
            subprocess.check_call(self.gpg_cmd + ["--export"], stdout=f)

    def get_pub_key(self, identity):
        return mini_buildd.misc.call(self.gpg_cmd + ["--armor", "--export={i}".format(i=identity)])

    def pub_keys_info(self):
        res = []
        for l in mini_buildd.misc.call(self.gpg_cmd + ["--list-public-keys", "--with-fingerprint", "--with-colons"]).splitlines():
            res.append(l.split(":"))
        return res

    def recv_key(self, keyserver, identity):
        return mini_buildd.misc.call(self.gpg_cmd + ["--armor", "--keyserver={ks}".format(ks=keyserver), "--recv-keys", identity])

    def add_pub_key(self, key):
        with tempfile.TemporaryFile() as t:
            t.write(key)
            t.seek(0)
            mini_buildd.misc.call(self.gpg_cmd + ["--import"], stdin=t)

    def add_keyring(self, keyring):
        self.gpg_cmd.append("--keyring={k}".format(k=keyring))

    def verify(self, signature, data=None):
        try:
            xtra_opts = [data] if data else []
            mini_buildd.misc.call(self.gpg_cmd + ["--verify", signature] + xtra_opts)
        except:
            raise Exception("GnuPG authorization failed on '{c}'".format(c=signature))

    def sign(self, file_name, identity=None):
        xtra_opts = ["--local-user={i}".format(i=identity)] if identity else []
        signed_file = file_name + ".signed"
        mini_buildd.misc.call(self.gpg_cmd + ["--armor", "--textmode", "--clearsign", "--output={f}".format(f=signed_file)] + xtra_opts + [file_name])
        os.rename(signed_file, file_name)


class GnuPG(BaseGnuPG):
    def __init__(self, template, fullname, email):
        super(GnuPG, self).__init__(home=os.path.join(mini_buildd.setup.HOME_DIR, ".gnupg"))
        self.template = """\
{t}
Name-Real: {n}
Name-Email: {e}
""".format(t=template, n=fullname, e=email)

    def prepare(self):
        if not self.get_pub_key():
            LOG.info("Generating GnuPG secret key (this might take some time)...")
            self.gen_secret_key(self.template)
            LOG.info("New GnuPG secret key prepared...")
        else:
            LOG.info("GnuPG key already prepared...")

    def unprepare(self):
        if os.path.exists(self.home):
            shutil.rmtree(self.home)
            LOG.info("GnuPG setup removed: {h}".format(h=self.home))

    def get_pub_key(self, identity=None):
        return super(GnuPG, self).get_pub_key("mini-buildd")

    def get_fingerprint(self):
        return super(GnuPG, self).get_fingerprint("mini-buildd")


class TmpGnuPG(BaseGnuPG):
    """
    >>> gnupg = TmpGnuPG()
    >>> gnupg.gen_secret_key("Key-Type: DSA\\nKey-Length: 1024\\nName-Email: test@key.org")
    >>> t = tempfile.NamedTemporaryFile()
    >>> t.write("A test file")
    >>> gnupg.sign(file_name=t.name, identity="test@key.org")
    >>> gnupg.verify(t.name)
    >>> pub_key = gnupg.get_pub_key(identity="test@key.org")
    >>> tgnupg = TmpGnuPG()
    >>> tgnupg.add_pub_key(pub_key)
    >>> tgnupg.verify(t.name)
    """
    def __init__(self):
        super(TmpGnuPG, self).__init__(home=tempfile.mkdtemp())

    def __del__(self):
        ".. todo:: Without this extra import, this might not work (python bug?). "
        from shutil import rmtree
        rmtree(self.home)


if __name__ == "__main__":
    mini_buildd.misc.setup_test_logging()

    import doctest
    doctest.testmod()
