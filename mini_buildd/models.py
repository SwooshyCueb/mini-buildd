# -*- coding: utf-8 -*-
import os, datetime, socket, urllib, logging

import django.db.models, django.contrib.admin, django.contrib.messages

import debian.deb822

log = logging.getLogger(__name__)

def msg_info(request, msg):
    django.contrib.messages.add_message(request, django.contrib.messages.INFO, msg)
    log.info(msg)


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


class Architecture(django.db.models.Model):
    name = django.db.models.CharField(primary_key=True, max_length=50)

    def __unicode__(self):
        return self.name


class Component(django.db.models.Model):
    name = django.db.models.CharField(primary_key=True, max_length=50)

    def __unicode__(self):
        return self.name


def source_scan(modeladmin, request, queryset):
    for s in queryset:
        s.mbd_scan(request)
source_scan.short_description = "(Re)scan selected sources"

class Source(django.db.models.Model):
    DESC_UNSCANNED = "please scan to find mirrors"

    origin = django.db.models.CharField(max_length=60, default="Debian")
    codename = django.db.models.CharField(max_length=60, default="sid")
    apt_key = django.db.models.TextField(default="", blank=True)

    mirrors = django.db.models.ManyToManyField(Mirror, null=True)
    description = django.db.models.CharField(max_length=100, editable=False, default=DESC_UNSCANNED)

    class Meta:
        unique_together = ("origin", "codename")
        ordering = ["origin", "codename"]

    class Admin(django.contrib.admin.ModelAdmin):
        search_fields = ["origin", "codename"]
        readonly_fields = ["mirrors", "description"]
        actions = [source_scan]

    def __unicode__(self):
        return self.origin + " '" + self.codename + "': " + self.description + " (" + str(len(self.mirrors.all())) + " mirrors)"

    def mbd_scan(self, request):
        log.info("Preparing source: {d}".format(d=self))
        self.description = self.DESC_UNSCANNED
        self.mirrors = []
        for m in Mirror.objects.all():
            try:
                log.info("Scanning mirror: {m}".format(m=m))
                release = m.mbd_download_release(self.codename)
                origin = release["Origin"]
                codename = release["Codename"]
                if self.origin == origin and self.codename == codename:
                    self.mirrors.add(m)
                    self.description = release["Description"]
                    self.save()
                    msg_info(request, "Mirror found: {m}".format(m=m))
                    # Auto-create new archs and components
                    for a in release["Architectures"].split(" "):
                        newArch, created = Architecture.objects.get_or_create(name=a)
                        if created:
                            msg_info(request, "Auto-adding new architecture: {a}".format(a=a))
                    for c in release["Components"].split(" "):
                        newComponent, created = Component.objects.get_or_create(name=c)
                        if created:
                            msg_info(request, "Auto-adding new component: {c}".format(c=c))
            except:
                log.info("Mirror {m} not for {s}".format(m=m, s=self))

    def get_mirror(self):
        ".. todo:: Returning first mirror only. Should return preferred one from mirror list."
        for m in self.mirrors.all():
            return m

    def get_apt_line(self, components="main contrib non-free"):
        m = self.get_mirror()
        return "deb {u} {d} {C}".format(u=m.url, d=self.codename, C=components)

    def get_apt_pin(self):
        return "release n=" + self.codename + ", o=" + self.origin



class PrioSource(django.db.models.Model):
    source = django.db.models.ForeignKey(Source)
    prio = django.db.models.IntegerField(default=1,
                               help_text="A apt pin priority value (see 'man apt_preferences')."
                               "Examples: 1=not automatic, 1001=downgrade'")

    class Meta:
        unique_together = ('source', 'prio')

    def __unicode__(self):
        return self.source.__unicode__() + ": Prio=" + str(self.prio)


class Suite(django.db.models.Model):
    name = django.db.models.CharField(
        primary_key=True, max_length=50,
        help_text="A suite to support, usually s.th. like 'unstable','testing' or 'stable'.")
    mandatory_version = django.db.models.CharField(
        max_length=50, default="~{rid}{nbv}+[1-9]",
        help_text="Mandatory version template; {rid}=repository id, {nbv}=numerical base distribution version.")

    migrates_from = django.db.models.ForeignKey('self', blank=True, null=True,
                                      help_text="Leave this blank to make this suite uploadable, or chose a suite where this migrates from.")
    not_automatic = django.db.models.BooleanField(default=True)
    but_automatic_upgrades = django.db.models.BooleanField(default=False)

    def __unicode__(self):
        return self.name + " (" + ("<= " + self.migrates_from.name if self.migrates_from else "uploadable") + ")"


class Layout(django.db.models.Model):
    name = django.db.models.CharField(primary_key=True, max_length=128,
                            help_text="Name for the layout.")
    suites = django.db.models.ManyToManyField(Suite)

    def __unicode__(self):
        return self.name

class Distribution(django.db.models.Model):
    """
    .. todo:: Distribution Model

       - limit to distribution?  limit_choices_to={'codename': 'sid'})
       - how to limit to source.kind?
    """
    base_source = django.db.models.ForeignKey(Source, primary_key=True)

    extra_sources = django.db.models.ManyToManyField(PrioSource, blank=True, null=True)

    def get_apt_sources_list(self):
        res = "# Base: {p}\n".format(p=self.base_source.get_apt_pin())
        res += self.base_source.get_apt_line() + "\n\n"
        for e in self.extra_sources.all():
            res += "# Extra: {p}\n".format(p=e.source.get_apt_pin())
            res += e.source.get_apt_line() + "\n"
        return res

    def __unicode__(self):
        ".. todo:: somehow indicate extra sources to visible name"
        return self.base_source.origin + ": " + self.base_source.codename


from mini_buildd import repository
class Repository(repository.Repository):
    pass

from mini_buildd import chroot
class Chroot(chroot.Chroot):
    pass

class FileChroot(chroot.FileChroot):
    pass

class LVMChroot(chroot.LVMChroot):
    pass

class LoopLVMChroot(chroot.LoopLVMChroot):
    pass

from mini_buildd import builder
class Builder(builder.Builder):
    pass

from mini_buildd import manager
class Manager(manager.Manager):
    pass

class Remote(django.db.models.Model):
    host = django.db.models.CharField(max_length=99, default=socket.getfqdn())

    def __unicode__(self):
        return "Remote: {h}".format(h=self.host)
