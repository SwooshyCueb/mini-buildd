# -*- coding: utf-8 -*-
import os, datetime, socket, urllib, logging

import django.db.models, django.contrib.admin, django.contrib.messages

import debian.deb822

from mini_buildd import gnupg

log = logging.getLogger(__name__)

class Mirror(django.db.models.Model):
    url = django.db.models.URLField(primary_key=True, max_length=512,
                                    default="http://ftp.debian.org/debian",
                                    help_text="The URL of an apt mirror/repository")

    class Meta:
        ordering = ["url"]
        verbose_name = "[A1] Mirror"

    class Admin(django.contrib.admin.ModelAdmin):
        search_fields = ["url"]

    def __unicode__(self):
        return self.url

    def mbd_download_release(self, dist):
        return debian.deb822.Release(urllib.urlopen(self.url + "/dists/" + dist + "/Release"))

django.contrib.admin.site.register(Mirror, Mirror.Admin)

class Architecture(django.db.models.Model):
    name = django.db.models.CharField(primary_key=True, max_length=50)

    def __unicode__(self):
        return self.name


class Component(django.db.models.Model):
    name = django.db.models.CharField(primary_key=True, max_length=50)

    def __unicode__(self):
        return self.name

from mini_buildd.models import StatusModel, msg_info, msg_warn, msg_error

class Source(StatusModel):
    # Identity
    origin = django.db.models.CharField(max_length=60, default="Debian",
                                        help_text="The exact string of the 'Origin' field of the resp. Release file.")
    codename = django.db.models.CharField(max_length=60, default="sid",
                                          help_text="The exact string of the 'Codename' field of the resp. Release file.")

    # Apt Secure
    apt_key_id = django.db.models.CharField(max_length=100, blank=True, default="",
                                            help_text="Give a key id here to retrieve the actual apt key automatically per configured keyserver.")
    apt_key = django.db.models.TextField(blank=True, default="",
                                         help_text="ASCII-armored apt key. Leave the key id blank if you fill this manually.")
    apt_key_fingerprint = django.db.models.TextField(blank=True, default="")

    # Automatic
    description = django.db.models.CharField(max_length=100, editable=False, blank=True, default="")
    mirrors = django.db.models.ManyToManyField(Mirror, null=True)
    components = django.db.models.ManyToManyField(Component, null=True)
    architectures = django.db.models.ManyToManyField(Architecture, null=True)

    class Meta(StatusModel.Meta):
        unique_together = ("origin", "codename")
        ordering = ["origin", "codename"]
        verbose_name = "[A2] Source"

    class Admin(StatusModel.Admin):
        search_fields = StatusModel.Admin.search_fields + ["origin", "codename"]
        readonly_fields = StatusModel.Admin.readonly_fields + ["mirrors", "components", "architectures", "description", "apt_key_fingerprint"]
        fieldsets = (
            ("Identity", {
                    "fields": ("origin", "codename")
                    }),
            ("Apt Secure", {
                    "fields": ("apt_key_id", "apt_key", "apt_key_fingerprint")
                    }),
            ("Automatic", {
                    "classes": ("collapse",),
                    "fields": ("description", "mirrors", "components", "architectures")
                    }),)

    def __unicode__(self):
        return self.mbd_id()+ ": " + self.description + " (" + str(len(self.mirrors.all())) + " mirrors)"

    def mbd_id(self):
        return self.origin + " '" + self.codename + "'"

    def mbd_prepare(self, request):
        self.mirrors = []
        if self.apt_key_id:
            from mini_buildd import daemon
            tg = gnupg.TmpGnuPG()
            tg.recv_key(daemon.get().gnupg_keyserver, self.apt_key_id)
            self.apt_key_fingerprint = tg.get_fingerprint(self.apt_key_id)
            self.apt_key = tg.get_pub_key(self.apt_key_id)
        for m in Mirror.objects.all():
            try:
                msg_info(request, "Scanning mirror: {m}".format(m=m))
                release = m.mbd_download_release(self.codename)
                origin = release["Origin"]
                codename = release["Codename"]
                if self.origin == origin and self.codename == codename:
                    msg_info(request, "Mirror found: {m}".format(m=m))
                    self.mirrors.add(m)
                    self.description = release["Description"]
                    # Set archs and components (may be auto-added)
                    for a in release["Architectures"].split(" "):
                        newArch, created = Architecture.objects.get_or_create(name=a)
                        if created:
                            msg_info(request, "Auto-adding new architecture: {a}".format(a=a))
                        self.architectures.add(newArch)
                    for c in release["Components"].split(" "):
                        newComponent, created = Component.objects.get_or_create(name=c)
                        if created:
                            msg_info(request, "Auto-adding new component: {c}".format(c=c))
                        self.components.add(newComponent)
            except Exception as e:
                msg_warn(request, "Mirror '{m}' error (ignoring): {e}".format(m=m, e=str(e)))

        if not len(self.mirrors.all()):
            raise Exception("{s}: No mirrors found (please add at least one)".format(s=self))

    def mbd_unprepare(self, request):
        self.mirrors = []
        self.components = []
        self.architectures = []
        self.description = ""
        self.apt_key = ""
        self.apt_key_fingerprint = ""

    def mbd_get_mirror(self):
        ".. todo:: Returning first mirror only. Should return preferred one from mirror list."
        for m in self.mirrors.all():
            return m

    def mbd_get_apt_line(self):
        ".. todo:: Merge components as configured per repo."
        m = self.mbd_get_mirror()
        components=""
        for c in self.components.all():
            components += c.name + " "
        return "deb {u} {d} {C}".format(u=m.url, d=self.codename, C=components)

    def mbd_get_apt_pin(self):
        return "release n=" + self.codename + ", o=" + self.origin

django.contrib.admin.site.register(Source, Source.Admin)


class PrioSource(django.db.models.Model):
    source = django.db.models.ForeignKey(Source)
    prio = django.db.models.IntegerField(default=1,
                                         help_text="A apt pin priority value (see 'man apt_preferences')."
                                         "Examples: 1=not automatic, 1001=downgrade'")

    class Meta:
        unique_together = ('source', 'prio')
        verbose_name = "[A3] PrioSource"

    def __unicode__(self):
        return self.source.__unicode__() + ": Prio=" + str(self.prio)

    def mbd_id(self):
        return "{i} (Prio {p})".format(i=self.source.mbd_id(), p=self.prio)

django.contrib.admin.site.register(PrioSource)
