# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import re
import tempfile
import shutil
import subprocess
import logging

import mini_buildd.misc
import mini_buildd.setup

LOG = logging.getLogger(__name__)


class Colons(object):
    """
    Provide a colon->name mapping for the gpg script-parsable '--with-colons' output.

    See /usr/share/doc/gnupg/DETAILS.gz.
    """
    def __init__(self, colons_line):
        self._colons = colons_line.split(":")

    def __unicode__(self):
        return "{t}: {k}: {u}".format(t=self.type, k=self.key_id, u=self.user_id)

    def _get(self, index):
        return mini_buildd.misc.list_get(self._colons, index, "")

    @property
    def type(self):
        return self._get(0)

    @property
    def key_id(self):
        return self._get(4)

    @property
    def creation_date(self):
        return self._get(5)

    @property
    def expiration_date(self):
        return self._get(6)

    @property
    def user_id(self):
        "fingerprint for 'fpr' type"
        return self._get(9)


class BaseGnuPG(object):
    def __init__(self, home):
        self.home = home
        self.gpg_cmd = ["gpg",
                        "--homedir={h}".format(h=home),
                        "--display-charset={charset}".format(charset=mini_buildd.setup.CHAR_ENCODING),
                        "--batch"]

    def gen_secret_key(self, template):
        with tempfile.TemporaryFile() as t:
            t.write(template.encode(mini_buildd.setup.CHAR_ENCODING))
            t.seek(0)
            mini_buildd.misc.call(self.gpg_cmd + ["--gen-key"], stdin=t)

    def export(self, dest_file, identity=""):
        with mini_buildd.misc.open_utf8(dest_file, "w") as f:
            subprocess.check_call(self.gpg_cmd + ["--export={i}".format(i=identity)], stdout=f)

    def get_pub_key(self, identity):
        return mini_buildd.misc.call(self.gpg_cmd + ["--armor", "--export={i}".format(i=identity)])

    def _get_colons(self, list_arg="--list-public-keys", type_regex=".*"):
        for line in mini_buildd.misc.call(self.gpg_cmd + [list_arg, "--with-fingerprint", "--with-colons"]).splitlines():
            colons = Colons(line)
            LOG.debug("{c}".format(c=colons))
            if re.match(type_regex, colons.type):
                yield colons

    def get_pub_colons(self, type_regex="pub"):
        return self._get_colons(list_arg="--list-public-keys", type_regex=type_regex)

    def get_sec_colons(self, type_regex="sec"):
        return self._get_colons(list_arg="--list-secret-keys", type_regex=type_regex)

    def get_first_sec_key(self):
        try:
            return self.get_sec_colons().next()
        except StopIteration:
            return Colons("")

    def get_first_sec_key_fingerprint(self):
        try:
            return self.get_sec_colons(type_regex="fpr").next()
        except StopIteration:
            return Colons("")

    def recv_key(self, keyserver, identity):
        return mini_buildd.misc.call(self.gpg_cmd + ["--armor", "--keyserver={ks}".format(ks=keyserver), "--recv-keys", identity])

    def add_pub_key(self, key):
        with tempfile.TemporaryFile() as t:
            t.write(key.encode(mini_buildd.setup.CHAR_ENCODING))
            t.seek(0)
            mini_buildd.misc.call(self.gpg_cmd + ["--import"], stdin=t)

    def add_keyring(self, keyring):
        if os.path.exists(keyring):
            self.gpg_cmd.append("--keyring={k}".format(k=keyring))
        else:
            LOG.warn("Skipping non-existing keyring file: {k}".format(k=keyring))

    def verify(self, signature, data=None):
        try:
            mini_buildd.misc.call(self.gpg_cmd + ["--verify", signature] + ([data] if data else []), error_log_on_fail=False)
        except:
            raise Exception("GnuPG authorization failed.")

    def sign(self, file_name, identity=None):
        # 1st: copy the unsigned file and add an extra new line
        # (Like 'debsign' from devscripts does: dpkg-source <= squeeze will have problems without the newline)
        unsigned_file = file_name + ".asc"
        shutil.copyfile(file_name, unsigned_file)
        with open(unsigned_file, "a") as unsigned:
            unsigned.write("\n")

        # 2nd: Sign the file copy
        signed_file = file_name + ".signed"
        mini_buildd.misc.call(self.gpg_cmd +
                              ["--armor", "--textmode", "--clearsign", "--output={f}".format(f=signed_file)] +
                              (["--local-user={i}".format(i=identity)] if identity else []) +
                              [unsigned_file])

        # 3rd: Success, move to orig file and cleanup
        os.rename(signed_file, file_name)
        os.remove(unsigned_file)


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

    def remove(self):
        if os.path.exists(self.home):
            shutil.rmtree(self.home)
            LOG.info("GnuPG setup removed: {h}".format(h=self.home))

    def get_pub_key(self, identity=None):
        return super(GnuPG, self).get_pub_key("mini-buildd")


class TmpGnuPG(BaseGnuPG, mini_buildd.misc.TmpDir):
    """
    >>> gnupg = TmpGnuPG()
    >>> gnupg.gen_secret_key("Key-Type: DSA\\nKey-Length: 1024\\nName-Real: Üdo Ümlaut\\nName-Email: test@key.org")

    >>> gnupg.get_first_sec_key().type
    u'sec'
    >>> gnupg.get_first_sec_key().user_id
    u'\\xdcdo \\xdcmlaut <test@key.org>'
    >>> gnupg.get_first_sec_key().key_id  #doctest: +ELLIPSIS
    u'...'
    >>> gnupg.get_first_sec_key_fingerprint().user_id  #doctest: +ELLIPSIS
    u'...'

    >>> t = tempfile.NamedTemporaryFile()
    >>> t.write("A test file\\n")
    >>> t.flush()
    >>> gnupg.sign(file_name=t.name, identity="test@key.org")
    >>> gnupg.verify(t.name)
    >>> pub_key = gnupg.get_pub_key(identity="test@key.org")
    >>> gnupg.close()
    >>> tgnupg = TmpGnuPG()
    >>> tgnupg.add_pub_key(pub_key)
    >>> tgnupg.verify(t.name)
    >>> tgnupg.close()
    """
    def __init__(self):
        mini_buildd.misc.TmpDir.__init__(self)
        super(TmpGnuPG, self).__init__(home=self.tmpdir)


if __name__ == "__main__":
    mini_buildd.misc.setup_console_logging()

    import doctest
    doctest.testmod()
