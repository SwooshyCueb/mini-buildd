# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import tempfile
import urllib2
import logging
import datetime
import contextlib
import copy

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
                                    default="http://ftp.debian.org/debian/",
                                    help_text="""
The URL of an apt archive (there must be a 'dists/' infrastructure below).

Use the 'directory' notation with exactly one trailing slash (like 'http://example.org/path/').
""")
    ping = django.db.models.FloatField(default=-1.0, editable=False)

    class Meta(mini_buildd.models.base.Model.Meta):
        ordering = ["url"]

    class Admin(mini_buildd.models.base.Model.Admin):
        search_fields = ["url"]
        exclude = ("extra_options",)

        @classmethod
        def _add_or_create(cls, request, url):
            if url:
                _obj, created = Archive.objects.get_or_create(url=url)
                if created:
                    mini_buildd.models.base.Model.mbd_msg_info(request, "Archive added: {a}".format(a=url))
                else:
                    mini_buildd.models.base.Model.mbd_msg_debug(request, "Archive already exists: {a}".format(a=url))

        def action_add_from_sources_list(self, request, _queryset):
            try:
                import aptsources.sourceslist
                for src in aptsources.sourceslist.SourcesList():
                    # These URLs come from the user. 'normalize' the uri first to have exactly one trailing slash.
                    self._add_or_create(request, src.uri.rstrip("/") + "/")
            except Exception as e:
                mini_buildd.setup.log_exception(LOG,
                                                "Failed to scan local sources.lists for default mirrors ('python-apt' not installed?)",
                                                e,
                                                level=logging.WARN)

        action_add_from_sources_list.short_description = "Add from sources.list [call with dummy selection]"

        def action_add_debian(self, request, _queryset):
            """
            Add internet Debian sources.
            """
            for url in ["http://ftp.debian.org/debian/",                  # Debian releases
                        "http://backports.debian.org/debian-backports/",  # Debian backports
                        "http://archive.debian.org/debian/",              # Archived Debian releases
                        "http://archive.debian.org/backports.org/",       # Archived (sarge, etch, lenny) backports
                        ]:
                self._add_or_create(request, url)
            mini_buildd.models.base.Model.mbd_msg_info(request, "Consider adapting these archives to you closest mirror(s); check netselect-apt.")

        action_add_debian.short_description = "Add Debian archive mirrors [call with dummy selection]"

        actions = [action_add_from_sources_list, action_add_debian]

    def save(self, *args, **kwargs):
        """
        Implicitely set the ping value on save.
        """
        self.mbd_ping(None)
        super(Archive, self).save(*args, **kwargs)

    def clean(self, *args, **kwargs):
        if self.url[-1] != "/" or self.url[-2] == "/":
            raise django.core.exceptions.ValidationError("The URL must have exactly one trailing slash (like 'http://example.org/path/').")
        super(Archive, self).clean(*args, **kwargs)

    def mbd_unicode(self):
        return "{u} (ping {p} ms)".format(u=self.url, p=self.ping)

    def mbd_download_release(self, source, gnupg):
        url = "{u}/dists/{d}/Release".format(u=self.url, d=source.codename)
        with tempfile.NamedTemporaryFile() as release:
            LOG.info("Downloading '{u}' to '{t}'".format(u=url, t=release.name))
            release.write(urllib2.urlopen(url).read())
            release.flush()
            release.seek(0)
            result = debian.deb822.Release(release)

            # Check origin and codename
            origin = result["Origin"]
            codename = result["Codename"]
            if not (source.origin == origin and source.codename == codename):
                raise Exception("Not for source '{so}:{sc}': Found '{o}:{c}'".format(so=source.origin, sc=source.codename, o=origin, c=codename))

            # Check signature
            with tempfile.NamedTemporaryFile() as signature:
                LOG.info("Downloading '{u}.gpg' to '{t}'".format(u=url, t=signature.name))
                signature.write(urllib2.urlopen(url + ".gpg").read())
                signature.flush()
                gnupg.verify(signature.name, release.name)

            # Ok, this is for this source
            return result

    def mbd_ping(self, request):
        """
        Ping and set the ping value.
        """
        try:
            t0 = datetime.datetime.now()
            urllib2.urlopen(self.url)
            delta = datetime.datetime.now() - t0
            self.ping = mini_buildd.misc.timedelta_total_seconds(delta) * (10 ** 3)
            self.mbd_msg_info(request, "{s}: Ping!".format(s=self))
        except:
            self.ping = -1.0
            self.mbd_msg_error(request, "{s}: Does not ping.".format(s=self))

        return self.ping


class Architecture(mini_buildd.models.base.Model):
    name = django.db.models.CharField(primary_key=True, max_length=50)

    def mbd_unicode(self):
        return self.name


class Component(mini_buildd.models.base.Model):
    name = django.db.models.CharField(primary_key=True, max_length=50)

    def mbd_unicode(self):
        return self.name


def cmp_components(component0, component1):
    """
    Get Debian components as string in a suitable order -- i.e.,
    'main' should be first, the others in alphabetical order.

    Basically only needed for reprepro's (broken?) default
    component guessing, which uses the first given component in
    the configuration.
    """
    if component0.name == "main":
        return -1
    return cmp(component0.name, component1.name)


class Source(mini_buildd.models.base.StatusModel):
    # Identity
    origin = django.db.models.CharField(max_length=60, default="Debian",
                                        help_text="The exact string of the 'Origin' field of the resp. Release file.")
    codename = django.db.models.CharField(max_length=60, default="sid",
                                          help_text="The exact string of the 'Codename' field of the resp. Release file.")

    # Apt Secure
    apt_keys = django.db.models.ManyToManyField(mini_buildd.models.gnupg.AptKey, blank=True,
                                                help_text="""\
Apt keys this source is signed with. Please add all keys the
resp. Release file is signed with (Run s.th. like
'gpg --verify Release.gpg Release'
manually run on a Debian system to be sure.
""")

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
        list_display = mini_buildd.models.base.StatusModel.Admin.list_display + ["origin", "codename"]
        search_fields = ["origin", "codename"]
        ordering = ["origin", "codename"]

        readonly_fields = ["codeversion", "archives", "components", "architectures", "description"]
        fieldsets = (
            ("Identity", {"fields": ("origin", "codename", "apt_keys")}),
            ("Extra", {"classes": ("collapse",), "fields": ("description", "codeversion", "codeversion_override", "archives", "components", "architectures")}),)

        def get_readonly_fields(self, _request, obj=None):
            "Forbid to change identity on existing source (usually a bad idea; repos/chroots that refer to us may break)."
            fields = copy.copy(self.readonly_fields)
            if obj:
                fields.append("origin")
                fields.append("codename")
            return fields

        @classmethod
        def _add_or_create(cls, request, origin, codename, keys):
            obj, created = Source.objects.get_or_create(origin=origin, codename=codename)
            if created:
                mini_buildd.models.base.Model.mbd_msg_info(request, "Source added: {s}".format(s=obj))
                for key_id in keys:
                    apt_key, _created = mini_buildd.models.gnupg.AptKey.objects.get_or_create(key_id=key_id)
                    obj.apt_keys.add(apt_key)
                    mini_buildd.models.base.Model.mbd_msg_info(request, "Apt key added: {k}".format(s=obj, k=apt_key))
                obj.save()
            else:
                mini_buildd.models.base.Model.mbd_msg_debug(request, "Source already exists: {s}".format(s=obj))

        def action_add_debian(self, request, _queryset):
            for origin, codename, keys in [("Debian", "etch", ["55BE302B", "ADB11277"]),
                                           ("Debian", "lenny", ["473041FA", "F42584E6"]),
                                           ("Debian", "squeeze", ["473041FA", "B98321F9"]),
                                           ("Debian", "wheezy", ["473041FA"]),
                                           ("Debian", "sid", ["473041FA"]),
                                           ("Backports.org archive", "etch-backports", ["16BA136C"]),
                                           ("Debian Backports", "lenny-backports", ["473041FA"]),
                                           ("Debian Backports", "squeeze-backports", ["473041FA"]),
                                           ]:
                self._add_or_create(request, origin, codename, keys)

        action_add_debian.short_description = "Add well-known Debian sources [call with dummy selection]"

        actions = [action_add_debian]

    def mbd_unicode(self):
        """
        .. note:: Workaround for django 1.4.3 bug/new behaviour.

            Since django 1.4.3, accessing 'self.archives.all()'
            does not work anymore: "maximum recursion depth
            exceeded" when trying to add a new source. Seems to
            be a django bug (?). Just not using it for now.
        """
        #return "{i}: {d}: {m} archives".format(i=self.mbd_id(), d=self.description, m=len(self.archives.all()))
        return "{o} '{c}': {d}".format(o=self.origin, c=self.codename, d=self.description)

    def mbd_get_archive(self):
        """
        Returns the fastest archive.
        """
        oa_list = self.archives.all().filter(ping__gte=0.0).order_by("ping")
        if oa_list:
            return oa_list[0]
        else:
            raise Exception("No (pinging) archive found. Please add appr. archive, or check network setup.")

    def mbd_get_apt_line(self, distribution):
        allowed_components = [c.name for c in distribution.components.all()]
        components = sorted([c for c in self.components.all() if c.name in allowed_components], cmp=cmp_components)
        return "deb {u} {d} {c}".format(
            u=self.mbd_get_archive().url,
            d=self.codename,
            c=" ".join([c.name for c in components]))

    def mbd_get_apt_pin(self):
        return "release n={c}, o={o}".format(c=self.codename, o=self.origin)

    def mbd_prepare(self, request):
        self.archives = []
        if not self.apt_keys.all():
            raise Exception("Please add apt keys to this source.")

        with contextlib.closing(mini_buildd.gnupg.TmpGnuPG()) as gpg:
            for k in self.apt_keys.all():
                gpg.add_pub_key(k.key)

            for m in Archive.objects.all():
                try:
                    # Get release if this archive serves us, else exception
                    release = m.mbd_download_release(self, gpg)

                    # Implicitely save ping value for this archive
                    m.save()
                    self.archives.add(m)
                    self.description = release["Description"]

                    # Set codeversion
                    self.codeversion = ""
                    if self.codeversion_override:
                        self.codeversion = self.codeversion_override
                        self.mbd_msg_warn(request, "{o}: Codeversion override active: {r}".format(o=self, r=self.codeversion_override))
                    else:
                        self.codeversion = mini_buildd.misc.guess_codeversion(release)
                        self.mbd_msg_info(request, "{o}: Codeversion guessed as: {r}".format(o=self, r=self.codeversion))

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
                    self.mbd_msg_info(request, "{o}: Added archive: {m}".format(o=self, m=m))

                except Exception as e:
                    self.mbd_msg_exception(request, "{m}: Not hosting us".format(m=m), e, level=django.contrib.messages.WARNING)

        self.mbd_check(request)

    def mbd_sync(self, request):
        self._mbd_sync_by_purge_and_create(request)

    def mbd_unprepare(self, _request):
        self.archives = []
        self.components = []
        self.architectures = []
        self.description = ""

    def mbd_check(self, _request):
        """
        Check that this source has at least one working archive left.
        """
        # Update all ping values
        for a in self.archives.all():
            a.save()
        self.mbd_get_archive()

    def mbd_get_dependencies(self):
        return self.apt_keys.all()

    def mbd_get_reverse_dependencies(self):
        "Return all chroots and repositories that use us."
        result = [c for c in self.chroot_set.all()]
        for d in self.distribution_set.all():
            for r in d.mbd_get_reverse_dependencies():
                result.append(r)
        return result


class PrioritySource(mini_buildd.models.base.Model):
    source = django.db.models.ForeignKey(Source)
    priority = django.db.models.IntegerField(default=1,
                                             help_text="A apt pin priority value (see 'man apt_preferences')."
                                             "Examples: 1=not automatic, 1001=downgrade'")

    class Meta(mini_buildd.models.base.Model.Meta):
        unique_together = ('source', 'priority')

    class Admin(mini_buildd.models.base.Model.Admin):
        exclude = ("extra_options",)

    def mbd_unicode(self):
        return "{i}: Priority={p}".format(i=self.source, p=self.priority)

    def mbd_get_apt_preferences(self):
        return "Package: *\nPin: {pin}\nPin-Priority: {prio}\n".format(pin=self.source.mbd_get_apt_pin(), prio=self.priority)
