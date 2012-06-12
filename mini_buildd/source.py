# -*- coding: utf-8 -*-
import os, datetime, socket, urllib, logging

import django.db.models, django.contrib.admin, django.contrib.messages

import debian.deb822

log = logging.getLogger(__name__)

class Mirror(django.db.models.Model):
    url = django.db.models.URLField(primary_key=True, max_length=512,
                                    default="http://ftp.debian.org/debian",
                                    help_text="The URL of an apt mirror/repository")

    class Meta:
        ordering = ["url"]

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
    origin = django.db.models.CharField(max_length=60, default="Debian")
    codename = django.db.models.CharField(max_length=60, default="sid")
    apt_key = django.db.models.TextField(blank=True, default="")

    mirrors = django.db.models.ManyToManyField(Mirror, null=True)
    description = django.db.models.CharField(max_length=100, editable=False, blank=True, default="")

    class Meta(StatusModel.Meta):
        unique_together = ("origin", "codename")
        ordering = ["origin", "codename"]

    class Admin(StatusModel.Admin):
        search_fields = StatusModel.Admin.search_fields + ["origin", "codename"]
        readonly_fields = StatusModel.Admin.readonly_fields + ["mirrors", "description"]

    def __unicode__(self):
        return self.get_status_display() + ": " + self.origin + " '" + \
            self.codename + "': " + self.description + " (" + str(len(self.mirrors.all())) + " mirrors)"

    def mbd_prepare(self, request):
        self.mirrors = []
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
                    # Don't care auto-creation of new archs and components
                    try:
                        for a in release["Architectures"].split(" "):
                            newArch, created = Architecture.objects.get_or_create(name=a)
                            if created:
                                msg_info(request, "Auto-adding new architecture: {a}".format(a=a))
                        for c in release["Components"].split(" "):
                            newComponent, created = Component.objects.get_or_create(name=c)
                            if created:
                                msg_info(request, "Auto-adding new component: {c}".format(c=c))
                    except Exception as e:
                        msg_info(request, "Ignoring arch/component auto-add error: {e}".format(e=str(e)))
            except Exception as e:
                msg_info(request, "Mirror {m} not for {s}: ${e}".format(m=m, s=self, e=str(e)))

    def mbd_unprepare(self, request):
        self.mirrors = []
        self.description = ""

    def mbd_get_mirror(self):
        ".. todo:: Returning first mirror only. Should return preferred one from mirror list."
        for m in self.mirrors.all():
            return m

    def mbd_get_apt_line(self, components="main contrib non-free"):
        m = self.mbd_get_mirror()
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

    def __unicode__(self):
        return self.source.__unicode__() + ": Prio=" + str(self.prio)

django.contrib.admin.site.register(PrioSource)
