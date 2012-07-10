# -*- coding: utf-8 -*-
import os
import tempfile
import shutil
import socket
import logging

import django.db.models
import django.contrib.admin
import django.contrib.messages

import mini_buildd.setup
import mini_buildd.misc

from mini_buildd.models import StatusModel, msg_info

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
            mini_buildd.misc.call(self.gpg_cmd + ["--gen-key"], stdin=t)

    def get_pub_key(self, id):
        return mini_buildd.misc.call(self.gpg_cmd + ["--armor", "--export={i}".format(i=id)])

    def pub_keys_info(self):
        res = []
        for l in mini_buildd.misc.call(self.gpg_cmd + ["--list-public-keys", "--with-fingerprint", "--with-colons"]).splitlines():
            log.info(l)
            res.append(l.split(":"))
        return res

    def recv_key(self, keyserver, id):
        return mini_buildd.misc.call(self.gpg_cmd + ["--armor", "--keyserver={ks}".format(ks=keyserver), "--recv-keys", id])

    def add_pub_key(self, key):
        with tempfile.TemporaryFile() as t:
            t.write(key)
            t.seek(0)
            mini_buildd.misc.call(self.gpg_cmd + ["--import"], stdin=t)

    def verify(self, signed_file, file=None):
        try:
            xtra_opts = [file] if file else []
            mini_buildd.misc.call(self.gpg_cmd + ["--verify", signed_file] + xtra_opts)
        except:
            raise Exception("GnuPG authorization failed on '{c}'".format(c=signed_file))

    def sign(self, file, id=None):
        xtra_opts = ["--local-user={i}".format(i=id)] if id else []
        signed_file = file + ".signed"
        mini_buildd.misc.call(self.gpg_cmd + ["--armor", "--textmode", "--clearsign", "--output={f}".format(f=signed_file)] + xtra_opts + [file])
        os.rename(signed_file, file)


class GnuPG(BaseGnuPG):
    def __init__(self, template):
        super(GnuPG, self).__init__(home=os.path.join(mini_buildd.setup.HOME_DIR, ".gnupg"))
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


class GnuPGPublicKey(StatusModel):
    key_id = django.db.models.CharField(max_length=100, blank=True, default="",
                                        help_text="Give a key id here to retrieve the actual key automatically per configured keyserver.")
    key = django.db.models.TextField(blank=True, default="",
                                     help_text="ASCII-armored Gnu PG public key. Leave the key id blank if you fill this manually.")

    key_long_id = django.db.models.CharField(max_length=254, blank=True, default="")
    key_created = django.db.models.CharField(max_length=254, blank=True, default="")
    key_expires = django.db.models.CharField(max_length=254, blank=True, default="")
    key_name = django.db.models.CharField(max_length=254, blank=True, default="")
    key_fingerprint = django.db.models.CharField(max_length=254, blank=True, default="")

    class Meta(StatusModel.Meta):
        abstract = True
        app_label = "mini_buildd"

    class Admin(StatusModel.Admin):
        search_fields = StatusModel.Admin.search_fields + ["key_id", "key_long_id", "key_name", "key_fingerprint"]
        readonly_fields = StatusModel.Admin.readonly_fields + ["key_long_id", "key_created", "key_expires", "key_name", "key_fingerprint"]

    def __unicode__(self):
        return u"{i}: {n}".format(i=self.key_id, n=self.key_name)

    def mbd_prepare(self, r):
        import mini_buildd.daemon
        gpg = TmpGnuPG()
        if self.key_id:
            # Receive key from keyserver
            gpg.recv_key(mini_buildd.daemon.get().model.gnupg_keyserver, self.key_id)
            self.key = gpg.get_pub_key(self.key_id)
        elif self.key:
            gpg.add_pub_key(self.key)

        for key in gpg.pub_keys_info():
            if key[0] == "pub":
                self.key_long_id = key[4]
                self.key_created = key[5]
                self.key_expires = key[6]
                self.key_name = key[9]
            if key[0] == "fpr":
                self.key_fingerprint = key[9]

    def mbd_unprepare(self, request):
        self.key_long_id = ""
        self.key_created = ""
        self.key_expires = ""
        self.key_name = ""
        self.key_fingerprint = ""
        if self.key_id:
            self.key = ""

if __name__ == "__main__":
    mini_buildd.misc.setup_test_logging()

    import doctest
    doctest.testmod()
