# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import tempfile
import urllib
import logging
import datetime

import django.db.models
import django.contrib.admin
import django.contrib.messages

import debian.deb822

import mini_buildd.gnupg

import mini_buildd.models.base
import mini_buildd.models.gnupg

LOG = logging.getLogger(__name__)


class Archive(mini_buildd.models.base.Model):
    url = django.db.models.URLField(primary_key=True, max_length=512,
                                    default="http://ftp.debian.org/debian",
                                    help_text="The URL of an apt archive (there must be a 'dists/' infrastructure below.")
    ping = django.db.models.FloatField(default=-1.0, editable=False)

    class Meta(mini_buildd.models.base.Model.Meta):
        ordering = ["url"]

    class Admin(mini_buildd.models.base.Model.Admin):
        search_fields = ["url"]

    def __unicode__(self):
        return "{u} (ping {p} ms)".format(u=self.url, p=self.ping)

    def save(self, *args, **kwargs):
        """
        Custom save(). Implicitely sets the ping value.
        """
        self.mbd_ping(None)
        super(Archive, self).save(*args, **kwargs)

    def mbd_download_release(self, dist, gnupg):
        url = "{u}/dists/{d}/Release".format(u=self.url, d=dist)
        with tempfile.NamedTemporaryFile() as release:
            LOG.info("Downloading '{u}' to '{t}'".format(u=url, t=release.name))
            release.write(urllib.urlopen(url).read())
            release.flush()
            if gnupg:
                with tempfile.NamedTemporaryFile() as signature:
                    LOG.info("Downloading '{u}.gpg' to '{t}'".format(u=url, t=signature.name))
                    signature.write(urllib.urlopen(url + ".gpg").read())
                    signature.flush()
                    gnupg.verify(signature.name, release.name)
            release.seek(0)
            return debian.deb822.Release(release)

    def mbd_ping(self, request):
        """
        Ping and set the ping value.
        """
        try:
            t0 = datetime.datetime.now()
            urllib.urlopen(self.url)
            delta = datetime.datetime.now() - t0
            self.ping = mini_buildd.misc.timedelta_total_seconds(delta) * (10 ** 3)
            self.mbd_msg_info(request, "{s}: Ping!".format(s=self))
        except:
            self.ping = -1.0
            self.mbd_msg_error(request, "{s}: Does not ping.".format(s=self))

        return self.ping


class Architecture(mini_buildd.models.base.Model):
    name = django.db.models.CharField(primary_key=True, max_length=50)

    def __unicode__(self):
        return self.name


class Component(mini_buildd.models.base.Model):
    name = django.db.models.CharField(primary_key=True, max_length=50)

    def __unicode__(self):
        return self.name


class Source(mini_buildd.models.base.StatusModel):
    # Identity
    origin = django.db.models.CharField(max_length=60, default="Debian",
                                        help_text="The exact string of the 'Origin' field of the resp. Release file.")
    codename = django.db.models.CharField(max_length=60, default="sid",
                                          help_text="The exact string of the 'Codename' field of the resp. Release file.")

    # Apt Secure
    apt_keys = django.db.models.ManyToManyField(mini_buildd.models.gnupg.AptKey, blank=True)

    # Extra
    description = django.db.models.CharField(max_length=100, editable=False, blank=True, default="")
    codeversion = django.db.models.CharField(max_length=50, editable=False, blank=True, default="")
    codeversion_override = django.db.models.CharField(
        max_length=50, blank=True, default="",
        help_text="Leave empty unless the automated way (via the Release file's 'Version' field) is broken. The codeversion is only used for base sources.")
    archives = django.db.models.ManyToManyField(Archive, blank=True)
    components = django.db.models.ManyToManyField(Component, blank=True)
    architectures = django.db.models.ManyToManyField(Architecture, blank=True)

    class Meta(mini_buildd.models.base.StatusModel.Meta):
        unique_together = ("origin", "codename")
        ordering = ["origin", "codename"]

    class Admin(mini_buildd.models.base.StatusModel.Admin):
        search_fields = ["origin", "codename"]
        readonly_fields = ["codeversion", "archives", "components", "architectures", "description"]
        fieldsets = (
            ("Identity", {"fields": ("origin", "codename", "apt_keys")}),
            ("Extra", {"classes": ("collapse",), "fields": ("description", "codeversion", "codeversion_override", "archives", "components", "architectures")}),)

    def __unicode__(self):
        return "{i}: {d}: {m} archives ({s})".format(i=self.mbd_id(), d=self.description, m=len(self.archives.all()), s=self.mbd_get_status_display())

    def mbd_id(self):
        return "{o} '{c}'".format(o=self.origin, c=self.codename)

    def mbd_get_archive(self):
        """
        Returns the fastest archive.
        """
        oa_list = self.archives.all().filter(ping__gte=0.0).order_by("ping")
        if oa_list:
            return oa_list[0]
        else:
            raise Exception("No (pinging) archive found. Please add appr. archive, or check network setup.")

    def mbd_get_apt_line(self):
        ".. todo:: Merge components as configured per repo."
        m = self.mbd_get_archive()
        components = ""
        for c in self.components.all():
            components += c.name + " "
        return "deb {u} {d} {C}".format(u=m.url, d=self.codename, C=components)

    def mbd_get_apt_pin(self):
        return "release n=" + self.codename + ", o=" + self.origin

    def mbd_prepare(self, request):
        self.archives = []
        gpg = mini_buildd.gnupg.TmpGnuPG() if self.apt_keys.all() else None
        for k in self.apt_keys.all():
            gpg.add_pub_key(k.key)

        for m in Archive.objects.all():
            self.mbd_msg_info(request, "Scanning archive: {m}".format(m=m))
            try:
                release = m.mbd_download_release(self.codename, gpg)
                origin = release["Origin"]
                codename = release["Codename"]
                if not (self.origin == origin and self.codename == codename):
                    raise Exception("Release says: origin={o}, codename={c}".format(o=origin, c=codename))

                self.mbd_msg_info(request, "Archive for us: {m}".format(m=m))
                self.archives.add(m)
                self.description = release["Description"]

                # Set codeversion
                self.codeversion = ""
                if self.codeversion_override:
                    self.codeversion = self.codeversion_override
                else:
                    try:
                        version = release["Version"].split(".")
                        self.codeversion = version[0] + version[1]
                    except:
                        self.codeversion = codename.upper()

                # Set architectures and components (may be auto-added)
                for a in release["Architectures"].split(" "):
                    new_arch, created = Architecture.objects.get_or_create(name=a)
                    if created:
                        self.mbd_msg_info(request, "Auto-adding new architecture: {a}".format(a=a))
                    self.architectures.add(new_arch)
                for c in release["Components"].split(" "):
                    new_component, created = Component.objects.get_or_create(name=c)
                    if created:
                        self.mbd_msg_info(request, "Auto-adding new component: {c}".format(c=c))
                    self.components.add(new_component)
            except Exception as e:
                self.mbd_msg_info(request, "{m}: Not for us: {e}".format(m=m, e=e))

        # Update ping value for all archives
        for a in self.archives.all():
            # Save will implicitely ping
            a.save()

        # Check if we still get an archive
        a = self.mbd_get_archive()
        self.mbd_msg_info(request, "{s}: Fastest archive is: '{a}'".format(s=self, a=a))

    def mbd_unprepare(self, _request):
        self.archives = []
        self.components = []
        self.architectures = []
        self.description = ""

    def mbd_check(self, request):
        self.mbd_prepare(request)

    def mbd_get_status_dependencies(self):
        dependencies = []
        for k in self.apt_keys.all():
            dependencies.append(k)
        return dependencies


class PrioritySource(mini_buildd.models.base.Model):
    source = django.db.models.ForeignKey(Source)
    priority = django.db.models.IntegerField(default=1,
                                             help_text="A apt pin priority value (see 'man apt_preferences')."
                                             "Examples: 1=not automatic, 1001=downgrade'")

    class Meta(mini_buildd.models.base.Model.Meta):
        unique_together = ('source', 'priority')

    def __unicode__(self):
        return "{i}: Priority={p}".format(i=self.source, p=self.priority)

    def mbd_id(self):
        return "{i} (prio={p})".format(i=self.source.mbd_id(), p=self.priority)
