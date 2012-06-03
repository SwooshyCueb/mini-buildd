# -*- coding: utf-8 -*-
import socket, os, logging

import django.db.models, django.contrib.admin

log = logging.getLogger(__name__)

class Mirror(django.db.models.Model):
    url = django.db.models.URLField(primary_key=True, max_length=512,
                          default="http://ftp.debian.org/debian",
                          help_text="The URL of an apt mirror/repository")

    class Meta:
        ordering = ['url']

    def __unicode__(self):
        return self.url

    class Admin(django.contrib.admin.ModelAdmin):
        search_fields = ['url']


class Source(django.db.models.Model):
    origin = django.db.models.CharField(max_length=100, default="Debian")
    codename = django.db.models.CharField(max_length=100, default="sid")
    mirrors = django.db.models.ManyToManyField('Mirror')

    class Meta:
        unique_together = ('origin', 'codename')
        ordering = ['origin', 'codename']

    def get_mirror(self):
        ".. todo:: Returning first mirror only. Should return preferred/working one from mirror list."
        for m in self.mirrors.all():
            return m

    def get_apt_line(self, components="main contrib non-free"):
        m = self.get_mirror()
        return "deb {u} {d} {C}".format(u=m.url, d=self.codename, C=components)

    def get_apt_pin(self):
        return "release n=" + self.codename + ", o=" + self.origin

    def __unicode__(self):
        return self.origin + ": " + self.codename + " [" + self.get_apt_pin() + "]"

    class Admin(django.contrib.admin.ModelAdmin):
        search_fields = ['origin', 'codename']


class PrioritisedSource(django.db.models.Model):
    source = django.db.models.ForeignKey(Source)
    prio = django.db.models.IntegerField(default=1,
                               help_text="A apt pin priority value (see 'man apt_preferences')."
                               "Examples: 1=not automatic, 1001=downgrade'")

    class Meta:
        unique_together = ('source', 'prio')

    def __unicode__(self):
        return self.source.__unicode__() + ": Prio=" + str(self.prio)


class Architecture(django.db.models.Model):
    arch = django.db.models.CharField(primary_key=True, max_length=50,
                            help_text="A valid Debian architecture (the output of 'dpkg --print-architecture' on the architecture)."
                            "Examples: 'i386', 'amd64', 'powerpc'")

    def __unicode__(self):
        return self.arch


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

    extra_sources = django.db.models.ManyToManyField(PrioritisedSource, blank=True, null=True)

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
