# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import urllib2
import contextlib
import logging

import django.db.models
import django.contrib.admin
import django.contrib.messages

import mini_buildd.misc
import mini_buildd.gnupg

import mini_buildd.models.base

from mini_buildd.models.msglog import MsgLog
LOG = logging.getLogger(__name__)


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

    def __unicode__(self):
        return "{i}: {n}".format(i=self.key_long_id if self.key_long_id else self.key_id, n=self.key_name)

    def clean(self, *args, **kwargs):
        super(GnuPGPublicKey, self).clean(*args, **kwargs)
        if self.key_id and len(self.key_id) < 8:
            raise django.core.exceptions.ValidationError("The key id, if given, must be at least 8 bytes  long")

    @classmethod
    def mbd_filter_key(cls, key_id):
        regex = r"{k}$".format(k=key_id[-8:])
        return cls.objects.filter(django.db.models.Q(key_long_id__iregex=regex) |
                                  django.db.models.Q(key_id__iregex=regex))

    def mbd_prepare(self, _request):
        with contextlib.closing(mini_buildd.gnupg.TmpGnuPG()) as gpg:
            if self.key_id:
                # Receive key from keyserver
                gpg.recv_key(self.mbd_get_daemon().model.gnupg_keyserver, self.key_id)
                self.key = gpg.get_pub_key(self.key_id)
            elif self.key:
                # Add key given explicitly
                gpg.add_pub_key(self.key)

            for colons in gpg.get_pub_colons(type_regex="^(pub|fpr)$"):
                if colons.type == "pub":
                    self.key_long_id = colons.key_id
                    self.key_created = colons.creation_date
                    self.key_expires = colons.expiration_date
                    self.key_name = colons.user_id
                if colons.type == "fpr":
                    self.key_fingerprint = colons.user_id
            # Update the user-given key id by it's long version
            self.key_id = self.key_long_id

    def mbd_remove(self, _request):
        self.key_long_id = ""
        self.key_created = ""
        self.key_expires = ""
        self.key_name = ""
        self.key_fingerprint = ""
        if self.key_id:
            self.key = ""

    def mbd_sync(self, request):
        self._mbd_remove_and_prepare(request)

    def mbd_check(self, _request):
        """
        Checks that we actually have the key and long_id. This should always be true after "prepare".
        """
        if not self.key and not self.key_long_id:
            raise Exception("GnuPG key with inconsistent state -- try remove,prepare to fix.")


class AptKey(GnuPGPublicKey):
    def clean(self, *args, **kwargs):
        super(AptKey, self).clean(*args, **kwargs)

        if self.key_id:
            matching_key = self.mbd_filter_key(self.key_id)
            if matching_key.count() > 0:
                raise django.core.exceptions.ValidationError("Another such key id already exists: {k}".format(k=matching_key[0]))


class KeyringKey(GnuPGPublicKey):
    """
    Abtract class for GnuPG keys that influence the daemon's keyring.

    This basically means changes to remotes and users may be
    done on the fly (without stopping the daemon), to make this
    maintenance practically usable.
    """
    class Meta(mini_buildd.models.base.StatusModel.Meta):
        abstract = True
        app_label = "mini_buildd"

    class Admin(GnuPGPublicKey.Admin):
        @classmethod
        def _mbd_on_change(cls, request, obj):
            "Notify the daemon keyring to update itself."
            if obj.mbd_get_daemon().keyrings:
                MsgLog(LOG, request).info("Scheduling keyrings update...")
                obj.mbd_get_daemon().keyrings.set_needs_update()

        @classmethod
        def _mbd_on_activation(cls, request, obj):
            cls._mbd_on_change(request, obj)

        @classmethod
        def _mbd_on_deactivation(cls, request, obj):
            cls._mbd_on_change(request, obj)


class Uploader(KeyringKey):
    user = django.db.models.OneToOneField(django.contrib.auth.models.User)
    may_upload_to = django.db.models.ManyToManyField("Repository", blank=True)

    class Admin(KeyringKey.Admin):
        search_fields = KeyringKey.Admin.search_fields + ["user"]
        readonly_fields = KeyringKey.Admin.readonly_fields + ["user"]
        filter_horizontal = ("may_upload_to",)

    def __unicode__(self):
        return "'{u}' may upload to '{r}' with key '{s}'".format(
            u=self.user,
            r=",".join([r.identity for r in self.may_upload_to.all()]),
            s=super(Uploader, self).__unicode__())


def cb_create_user_profile(sender, instance, created, **kwargs):
    "Automatically create a user profile with every user that is created"
    if created:
        Uploader.objects.create(user=instance)
django.db.models.signals.post_save.connect(cb_create_user_profile, sender=django.contrib.auth.models.User)


class Remote(KeyringKey):
    http = django.db.models.CharField(primary_key=True, max_length=255, default=":8066",
                                      help_text="""\
'hostname:port' of the remote instance's http server.
""")

    wake_command = django.db.models.CharField(max_length=255, default="", blank=True, help_text="For future use.")

    class Admin(KeyringKey.Admin):
        search_fields = KeyringKey.Admin.search_fields + ["http"]
        readonly_fields = KeyringKey.Admin.readonly_fields + ["key", "key_id", "pickled_data"]

    def __unicode__(self):
        status = self.mbd_get_status()
        return "{h}: {c}".format(h=self.http,
                                 c=status.chroots_str())

    def mbd_get_status(self, update=False):
        if update:
            url = "http://{h}/mini_buildd/api?command=status&output=python".format(h=self.http)
            self.mbd_set_pickled_data_pickled(urllib2.urlopen(url, timeout=10).read())
        return self.mbd_get_pickled_data(default=mini_buildd.api.Status({}))

    def mbd_prepare(self, request):
        url = "http://{h}/mini_buildd/api?command=getkey&output=plain".format(h=self.http)
        MsgLog(LOG, request).info("Downloading '{u}'...".format(u=url))

        # We prepare the GPG data from downloaded key data, so key_id _must_ be empty (see super(mbd_prepare))
        self.key_id = ""
        self.key = urllib2.urlopen(url).read()

        if self.key:
            MsgLog(LOG, request).warn("Downloaded remote key integrated: Please check key manually before activation!")
        else:
            raise Exception("Empty remote key from '{u}' -- maybe the remote is not prepared yet?".format(u=url))
        super(Remote, self).mbd_prepare(request)

    def mbd_remove(self, request):
        super(Remote, self).mbd_remove(request)
        self.mbd_set_pickled_data(mini_buildd.api.Status({}))
        MsgLog(LOG, request).info("Remote key and state removed.")

    def mbd_check(self, request):
        """
        Check whether the remote mini-buildd is up, running and serving for us.
        """
        super(Remote, self).mbd_check(request)
        status = self.mbd_get_status(update=True)

        if not self.mbd_get_daemon().model.mbd_get_http_hopo().string in status.remotes:
            raise Exception("Remote '{r}': does not know us.".format(r=self.http))

        if not status.running:
            raise Exception("Remote '{r}': is down.".format(r=self.http))
