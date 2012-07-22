# -*- coding: utf-8 -*-
import os
import tempfile
import shutil
import subprocess

import django.db.models
import django.contrib.admin
import django.contrib.messages

import mini_buildd.misc
import mini_buildd.setup

from mini_buildd.models import StatusModel, msg_info


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

    def prepare(self, request):
        if not self.get_pub_key():
            msg_info(request, "Generating GnuPG secret key (this might take some time)...")
            self.gen_secret_key(self.template)
            msg_info(request, "New GnuPG secret key prepared...")
        else:
            msg_info(request, "GnuPG key already prepared...")

    def unprepare(self, request):
        if os.path.exists(self.home):
            shutil.rmtree(self.home)
            msg_info(request, "GnuPG setup removed: {h}".format(h=self.home))

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
        from shutil import rmtree
        rmtree(self.home)


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

    def mbd_prepare(self, _request):
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

    def mbd_unprepare(self, _request):
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
