# -*- coding: utf-8 -*-
import os, datetime, socket, tempfile, urllib, logging

import django.db.models, django.contrib.admin, django.contrib.messages

import debian.deb822

from mini_buildd import gnupg

from mini_buildd.models import Model, StatusModel, AptKey, msg_info, msg_warn, msg_error

log = logging.getLogger(__name__)

class Mirror(Model):
    url = django.db.models.URLField(primary_key=True, max_length=512,
                                    default="http://ftp.debian.org/debian",
                                    help_text="The URL of an apt mirror/repository")

    class Meta:
        ordering = ["url"]

    class Admin(django.contrib.admin.ModelAdmin):
        search_fields = ["url"]

    def __unicode__(self):
        return self.url

    def mbd_download_release(self, dist, gnupg):
        url = self.url + "/dists/" + dist + "/Release"
        with tempfile.NamedTemporaryFile() as release:
            log.info("Downloading '{u}' to '{t}'".format(u=url, t=release.name))
            release.write(urllib.urlopen(url).read())
            release.flush()
            if gnupg:
                with tempfile.NamedTemporaryFile() as signature:
                    log.info("Downloading '{u}.gpg' to '{t}'".format(u=url, t=signature.name))
                    signature.write(urllib.urlopen(url + ".gpg").read())
                    signature.flush()
                    gnupg.verify(signature.name, release.name)
            release.seek(0)
            return debian.deb822.Release(release)

django.contrib.admin.site.register(Mirror, Mirror.Admin)

class Architecture(Model):
    name = django.db.models.CharField(primary_key=True, max_length=50)

    def __unicode__(self):
        return self.name


class Component(Model):
    name = django.db.models.CharField(primary_key=True, max_length=50)

    def __unicode__(self):
        return self.name

class Source(StatusModel):
    # Identity
    origin = django.db.models.CharField(max_length=60, default="Debian",
                                        help_text="The exact string of the 'Origin' field of the resp. Release file.")
    codename = django.db.models.CharField(max_length=60, default="sid",
                                          help_text="The exact string of the 'Codename' field of the resp. Release file.")

    # Apt Secure
    apt_keys = django.db.models.ManyToManyField(AptKey, blank=True)

    # Extra
    description = django.db.models.CharField(max_length=100, editable=False, blank=True, default="")
    codeversion = django.db.models.CharField(max_length=50, editable=False, blank=True, default="")
    codeversion_override = django.db.models.CharField(
        max_length=50, blank=True, default="",
        help_text="Leave empty unless the automated way (via the Release file's 'Version' field) is broken. The codeversion is only used for base sources.")
    mirrors = django.db.models.ManyToManyField(Mirror, null=True)
    components = django.db.models.ManyToManyField(Component, null=True)
    architectures = django.db.models.ManyToManyField(Architecture, null=True)

    class Meta(StatusModel.Meta):
        unique_together = ("origin", "codename")
        ordering = ["origin", "codename"]

    class Admin(StatusModel.Admin):
        search_fields = StatusModel.Admin.search_fields + ["origin", "codename"]
        readonly_fields = StatusModel.Admin.readonly_fields + ["codeversion", "mirrors", "components", "architectures", "description"]
        fieldsets = (
            ("Identity", {
                    "fields": ("origin", "codename", "apt_keys")
                    }),
            ("Extra", {
                    "classes": ("collapse",),
                    "fields": ("description", "codeversion", "codeversion_override", "mirrors", "components", "architectures")
                    }),)

    def __unicode__(self):
        return u"{i}: {d} ({m} mirrors)".format(i=self.mbd_id(), d=self.description, m=len(self.mirrors.all()))

    def mbd_id(self):
        return "{o} '{c}'".format(o=self.origin, c=self.codename)

    def mbd_prepare(self, request):
        self.mirrors = []
        gpg = gnupg.TmpGnuPG() if self.apt_keys.all() else None
        for k in self.apt_keys.all():
            gpg.add_pub_key(k.key)

        for m in Mirror.objects.all():
            try:
                msg_info(request, "Scanning mirror: {m}".format(m=m))
                release = m.mbd_download_release(self.codename, gpg)
                origin = release["Origin"]
                codename = release["Codename"]

                if self.origin == origin and self.codename == codename:
                    msg_info(request, "Mirror found: {m}".format(m=m))
                    self.mirrors.add(m)
                    self.description = release["Description"]

                    # Set codeversion
                    self.codeversion = ""
                    if self.codeversion_override:
                        self.codeversion = self.codeversion_override
                    else:
                        try:
                            version = release["Version"].split(u".")
                            self.codeversion = version[0] + version[1]
                        except:
                            self.codeversion = codename.upper()

                    # Set architectures and components (may be auto-added)
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

    def mbd_get_mirror(self):
        ".. todo:: Returning first mirror only. Should return preferred one from mirror list, and fail if no mirrors found."
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


class PrioritySource(Model):
    source = django.db.models.ForeignKey(Source)
    priority = django.db.models.IntegerField(default=1,
                                             help_text="A apt pin priority value (see 'man apt_preferences')."
                                             "Examples: 1=not automatic, 1001=downgrade'")

    class Meta:
        unique_together = ('source', 'priority')

    def __unicode__(self):
        return u"{i}: Priority={p}".format(i=self.source.__unicode__(), p=self.priority)

    def mbd_id(self):
        return u"{i} (prio={p})".format(i=self.source.mbd_id(), p=self.priority)

django.contrib.admin.site.register(PrioritySource)
