# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import urllib2
import contextlib

import django.db.models
import django.contrib.admin
import django.contrib.messages

import mini_buildd.misc
import mini_buildd.gnupg

import mini_buildd.models.base


class GnuPGPublicKey(mini_buildd.models.base.StatusModel):
    key_id = django.db.models.CharField(max_length=100, blank=True, default="",
                                        help_text="Give a key id here to retrieve the actual key automatically per configured keyserver.")
    key = django.db.models.TextField(blank=True, default="",
                                     help_text="ASCII-armored GnuPG public key. Leave the key id blank if you fill this manually.")

    key_long_id = django.db.models.CharField(max_length=254, blank=True, default="")
    key_created = django.db.models.CharField(max_length=254, blank=True, default="")
    key_expires = django.db.models.CharField(max_length=254, blank=True, default="")
    key_name = django.db.models.CharField(max_length=254, blank=True, default="")
    key_fingerprint = django.db.models.CharField(max_length=254, blank=True, default="")

    class Meta(mini_buildd.models.base.StatusModel.Meta):
        abstract = True
        app_label = "mini_buildd"

    class Admin(mini_buildd.models.base.StatusModel.Admin):
        search_fields = ["key_id", "key_long_id", "key_name", "key_fingerprint"]
        readonly_fields = ["key_long_id", "key_created", "key_expires", "key_name", "key_fingerprint"]
        exclude = ("extra_options",)

    def mbd_unicode(self):
        return "{i}: {n}".format(i=self.key_long_id if self.key_long_id else self.key_id, n=self.key_name)

    def mbd_prepare(self, _request):
        with contextlib.closing(mini_buildd.gnupg.TmpGnuPG()) as gpg:
            if self.key_id:
                # Receive key from keyserver
                gpg.recv_key(self.mbd_get_daemon().model.gnupg_keyserver, self.key_id)
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

    def mbd_remove(self, _request):
        self.key_long_id = ""
        self.key_created = ""
        self.key_expires = ""
        self.key_name = ""
        self.key_fingerprint = ""
        if self.key_id:
            self.key = ""

    def mbd_sync(self, request):
        self._mbd_sync_by_purge_and_create(request)

    def mbd_check(self, _request):
        """
        Checks that we actually have the key and long_id. This should always be true after "prepare".
        """
        if not self.key and not self.key_long_id:
            raise Exception("GnuPG key with inconsistent state -- try remove,prepare to fix.")


class AptKey(GnuPGPublicKey):
    pass


class Uploader(GnuPGPublicKey):
    user = django.db.models.OneToOneField(django.contrib.auth.models.User)
    may_upload_to = django.db.models.ManyToManyField("Repository", blank=True)

    class Admin(GnuPGPublicKey.Admin):
        search_fields = GnuPGPublicKey.Admin.search_fields + ["user"]
        readonly_fields = GnuPGPublicKey.Admin.readonly_fields + ["user"]

    def mbd_unicode(self):
        return "'{u}': {s}".format(u=self.user, s=super(Uploader, self).mbd_unicode())


def cb_create_user_profile(sender, instance, created, **kwargs):
    "Automatically create a user profile with every user that is created"
    if created:
        Uploader.objects.create(user=instance)
django.db.models.signals.post_save.connect(cb_create_user_profile, sender=django.contrib.auth.models.User)


class Remote(GnuPGPublicKey):
    http = django.db.models.CharField(primary_key=True, max_length=255, default=":8066",
                                      help_text="""\
'hostname:port' of the remote instance's http server.
""")

    wake_command = django.db.models.CharField(max_length=255, default="", blank=True, help_text="For future use.")

    class Admin(GnuPGPublicKey.Admin):
        search_fields = GnuPGPublicKey.Admin.search_fields + ["http"]
        readonly_fields = GnuPGPublicKey.Admin.readonly_fields + ["key", "key_id", "pickled_data"]

    def mbd_unicode(self):
        status = self.mbd_get_status()
        return "{h}: {c}".format(h=self.http,
                                 c=status.chroots_str())

    def mbd_get_status(self, update=False):
        if update:
            url = "http://{h}/mini_buildd/api?command=status&output=python".format(h=self.http)
            self.pickled_data = urllib2.urlopen(url, timeout=10).read()
        return self.mbd_get_pickled_data(default=mini_buildd.api.Status({}))

    def mbd_prepare(self, request):
        url = "http://{h}/mini_buildd/api?command=getkey&output=plain".format(h=self.http)
        self.mbd_msg_info(request, "Downloading '{u}'...".format(u=url))
        self.key = urllib2.urlopen(url).read()
        if self.key:
            self.mbd_msg_warn(request, "Downloaded remote key integrated: Please check key manually before activation!")
        else:
            raise Exception("Empty remote key from '{u}' -- maybe the remote is not prepared yet?".format(u=url))
        super(Remote, self).mbd_prepare(request)

    def mbd_remove(self, request):
        super(Remote, self).mbd_remove(request)
        self.pickled_data = ""
        self.mbd_msg_info(request, "Remote key and state removed.")

    def mbd_check(self, _request):
        """
        Check whether the remote mini-buildd is running.
        """
        super(Remote, self).mbd_check(_request)
        self.mbd_get_status(update=True)
