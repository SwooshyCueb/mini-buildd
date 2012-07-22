# -*- coding: utf-8 -*-
import django.db.models
import django.contrib.admin
import django.contrib.messages

from mini_buildd.models import StatusModel


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
        import mini_buildd.gnupg
        gpg = mini_buildd.gnupg.TmpGnuPG()
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
