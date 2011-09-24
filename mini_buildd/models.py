# -*- coding: utf-8 -*-
import socket, platform, urllib

from debian import deb822

from django.db import models
from django.core.exceptions import ValidationError
from django.contrib import admin

import mini_buildd

class Mirror(models.Model):
    url = models.URLField(primary_key=True, max_length=512,
                          default="http://ftp.debian.org/debian",
                          help_text="The URL of an apt mirror/repository")

    class Meta:
        ordering = ['url']

    def __unicode__(self):
        return self.url

    class Admin(admin.ModelAdmin):
        search_fields = ['url']


class Source(models.Model):
    origin = models.CharField(max_length=100, default="Debian")
    codename = models.CharField(max_length=100, default="sid")
    mirrors = models.ManyToManyField('Mirror')

    class Meta:
        unique_together = ('origin', 'codename')
        ordering = ['origin', 'codename']

    def get_apt_lines(self, kind="deb", components="main contrib non-free"):
        apt_lines = []
        for m in self.mirrors.all():
            apt_lines.append(kind + ' ' if kind else '' + m.url + ' ' + self.codename + ' ' + components)
        mini_buildd.log.debug(str(apt_lines))
        return apt_lines

    def get_apt_pin(self):
        return "release n=" + self.codename + ", o=" + self.origin

    def __unicode__(self):
        return self.origin + ": " + self.codename + " [" + self.get_apt_pin() + "]"

    class Admin(admin.ModelAdmin):
        search_fields = ['origin', 'codename']


class PrioritisedSource(models.Model):
    source = models.ForeignKey(Source)
    prio = models.IntegerField(default=1,
                               help_text="A apt pin priority value (see 'man apt_preferences')."
                               "Examples: 1=not automatic, 1001=downgrade'")

    class Meta:
        unique_together = ('source', 'prio')

    def __unicode__(self):
        return self.source.__unicode__() + ": Prio=" + str(self.prio)


class Architecture(models.Model):
    arch = models.CharField(primary_key=True, max_length=50,
                            help_text="A valid Debian architecture (the output of 'dpkg --print-architecture' on the architecture)."
                            "Examples: 'i386', 'amd64', 'powerpc'")

    def __unicode__(self):
        return self.arch


class Builder(models.Model):
    host = models.CharField(max_length=99, default=socket.getfqdn())
    arch = models.ForeignKey(Architecture)
    parallel = models.IntegerField(default=1,
                                   help_text="Degree of parallelism this builder supports.")

    def __unicode__(self):
        return self.host + " building " + self.arch.arch

    class Meta:
        unique_together = ('host', 'arch')


class Suite(models.Model):
    name = models.CharField(primary_key=True, max_length=49,
                            help_text="A suite to support, usually s.th. like 'unstable','testing' or 'stable'.")
    migrates_from = models.ForeignKey('self', blank=True, null=True,
                                      help_text="Leave this blank to make this suite uploadable, or chose a suite where this migrates from.")

    def __unicode__(self):
        return self.name + " (" + ("<= " + self.migrates_from.name if self.migrates_from else "uploadable") + ")"


class Layout(models.Model):
    name = models.CharField(primary_key=True, max_length=128,
                            help_text="Name for the layout.")
    suites = models.ManyToManyField(Suite)

    def __unicode__(self):
        return self.name


class Distribution(models.Model):
    # @todo: limit to distribution?  limit_choices_to={'codename': 'sid'})
    base_source = models.ForeignKey(Source, primary_key=True)
    # @todo: how to limit to source.kind?
    extra_sources = models.ManyToManyField(PrioritisedSource, blank=True, null=True)

    def __unicode__(self):
        # @todo: somehow indicate extra sources to visible name
        return self.base_source.origin + ": " + self.base_source.codename

class Repository(models.Model):
    id = models.CharField(primary_key=True, max_length=50, default=socket.gethostname())
    host = models.CharField(max_length=100, default=socket.getfqdn())

    layout = models.ForeignKey(Layout)
    dists = models.ManyToManyField(Distribution)
    archs = models.ManyToManyField(Architecture)

    apt_allow_unauthenticated = models.BooleanField(default=False)
    mail = models.EmailField(blank=True)
    extdocurl = models.URLField(blank=True)

    def __unicode__(self):
        return self.id

    # Temporarily, restrict this to one instance
    def clean(self):
        model = self.__class__
        if (model.objects.count() > 0 and self.id != model.objects.get().id):
            raise ValidationError("This is temporarily restricted  to 1 %s instance" % model.__name__)
