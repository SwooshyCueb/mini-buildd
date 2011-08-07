import socket, platform

from django.db import models

class AptLine(models.Model):
    line = models.CharField(primary_key=True, max_length=512, default="http://ftp.debian.org/debian/ sid main contrib non-free")
    def __unicode__(self):
        return self.line

class Distribution(models.Model):
    codename = models.CharField(primary_key=True, max_length=99, default="sid")
    apt_line = models.ForeignKey(AptLine, default="http://ftp.debian.org/debian/ HUH main contrib non-free")
    def __unicode__(self):
        return self.codename + " (" + self.apt_line.line + ")"

class Architecture(models.Model):
    arch = models.CharField(primary_key=True, max_length=50, default="i386")
    def __unicode__(self):
        return self.arch

class Builder(models.Model):
    hostname = models.CharField(max_length=99, default=socket.getfqdn())
    arch = models.ForeignKey(Architecture)
    deb_build_options = models.CharField(max_length=160, default="parallel=1")
    class Meta:
        unique_together = ("hostname", "arch")
    def __unicode__(self):
        return self.hostname + " building " + self.arch.arch

class Repository(models.Model):
    id = models.CharField(primary_key=True, max_length=50, default=socket.gethostname())
    rephost = models.CharField(max_length=100, default=socket.getfqdn())
    dists = models.ManyToManyField(Distribution)
    archs = models.ManyToManyField(Architecture)
    #archall = models.ForeignKey(Architecture)
    apt_allow_unauthenticated = models.BooleanField(default=False)
    mail = models.EmailField(max_length=99)
    extdocurl = models.URLField(max_length=99)
    extra_sources = models.ForeignKey(AptLine, default="http://ftp.debian.org/debian/ HUH main contrib non-free")

    def __unicode__(self):
        return self.id
