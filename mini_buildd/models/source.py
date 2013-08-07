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

from mini_buildd.models.msglog import MsgLog
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
        def _mbd_get_or_create(cls, msglog, url):
            if url:
                Archive.mbd_get_or_create(msglog, url=url)

        @classmethod
        def mbd_meta_add_from_sources_list(cls, msglog):
            "Scan local sources list and add all archives found there."
            try:
                import aptsources.sourceslist
                for src in aptsources.sourceslist.SourcesList():
                    # These URLs come from the user. 'normalize' the uri first to have exactly one trailing slash.
                    cls._mbd_get_or_create(msglog, src.uri.rstrip("/") + "/")
            except Exception as e:
                mini_buildd.setup.log_exception(LOG,
                                                "Failed to scan local sources.lists for default mirrors ('python-apt' not installed?)",
                                                e,
                                                level=logging.WARN)

        @classmethod
        def mbd_meta_add_debian(cls, msglog):
            "Add internet Debian archive sources."
            for url in ["http://ftp.debian.org/debian/",                  # Debian releases
                        "http://backports.debian.org/debian-backports/",  # Debian backports, <= squeeze
                        "http://archive.debian.org/debian/",              # Archived Debian releases
                        "http://archive.debian.org/backports.org/",       # Archived (sarge, etch, lenny) backports
                        ]:
                cls._mbd_get_or_create(msglog, url)
            msglog.info("Consider adding archives with your local or closest mirrors; check 'netselect-apt'.")

        @classmethod
        def mbd_meta_add_ubuntu(cls, msglog):
            "Add internet Ubuntu archive sources."
            for url in ["http://danava.canonical.com/ubuntu/",            # Ubuntu releases
                        ]:
                cls._mbd_get_or_create(msglog, url)
            msglog.info("Consider replacing these archives with you closest mirror(s); check netselect-apt.")

    def save(self, *args, **kwargs):
        "Implicitely set the ping value on save."
        self.mbd_ping(None)
        super(Archive, self).save(*args, **kwargs)

    def clean(self, *args, **kwargs):
        if self.url[-1] != "/" or self.url[-2] == "/":
            raise django.core.exceptions.ValidationError("The URL must have exactly one trailing slash (like 'http://example.org/path/').")
        super(Archive, self).clean(*args, **kwargs)

    def mbd_unicode(self):
        return "{u} (ping {p} ms)".format(u=self.url, p=self.ping)

    def mbd_download_release(self, source, gnupg):
        dist, codename = source.mbd_parse_codename()

        url = "{u}/dists/{d}/Release".format(u=self.url, d=dist)
        with tempfile.NamedTemporaryFile() as release_file:
            LOG.info("Downloading '{u}' to '{t}'".format(u=url, t=release_file.name))
            release_file.write(urllib2.urlopen(url).read())
            release_file.flush()
            release_file.seek(0)
            release = debian.deb822.Release(release_file)

            # Check identity: origin, codename
            if not (source.origin == release["Origin"] and codename == release["Codename"]):
                raise Exception("Not for source '{so}:{sc}': Found '{o}:{d}/{c}:{s}'".format(so=source.origin,
                                                                                             sc=source.codename,
                                                                                             d=dist,
                                                                                             o=release["Origin"],
                                                                                             c=release["Codename"]))

            # Check signature
            with tempfile.NamedTemporaryFile() as signature:
                LOG.info("Downloading '{u}.gpg' to '{t}'".format(u=url, t=signature.name))
                signature.write(urllib2.urlopen(url + ".gpg").read())
                signature.flush()
                gnupg.verify(signature.name, release_file.name)

            # Ok, this is for this source
            return release

    def mbd_ping(self, request):
        "Ping and set the ping value."
        try:
            t0 = datetime.datetime.now()
            urllib2.urlopen(self.url)
            delta = datetime.datetime.now() - t0
            self.ping = mini_buildd.misc.timedelta_total_seconds(delta) * (10 ** 3)
            MsgLog(LOG, request).info("{s}: Ping!".format(s=self))
        except:
            self.ping = -1.0
            MsgLog(LOG, request).error("{s}: Does not ping.".format(s=self))

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
                                          help_text="""\
Source identifier in the form 'DIST[/CODENAME]'.<br />
<br />
<em>DIST</em>: The distribution name, i.e., the name of the directory below 'dist/' in Debian
archives; usually this is identical with the codename in the Release file.
<br />
<em>CODENAME</em>: The codename as given in the Release file in case it differs from DIST.
""")

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
        def _mbd_get_or_create(cls, msglog, origin, codename, keys):
            obj, created = Source.mbd_get_or_create(msglog, origin=origin, codename=codename)
            if created:
                for key_id in keys:
                    apt_key, _created = mini_buildd.models.gnupg.AptKey.mbd_get_or_create(msglog, key_id=key_id)
                    obj.apt_keys.add(apt_key)
                obj.save()

        @classmethod
        def mbd_meta_add_debian(cls, msglog):
            "Add well-known Debian sources"
            for origin, codename, keys in [("Debian", "etch", ["55BE302B", "ADB11277"]),
                                           ("Debian", "lenny", ["473041FA", "F42584E6"]),
                                           ("Debian", "squeeze", ["473041FA", "B98321F9"]),
                                           ("Debian", "wheezy", ["473041FA"]),
                                           ("Debian", "jessie", ["473041FA", "46925553"]),
                                           ("Debian", "sid", ["473041FA", "46925553"]),
                                           ("Backports.org archive", "etch-backports", ["16BA136C"]),
                                           ("Debian Backports", "lenny-backports", ["473041FA"]),
                                           ("Debian Backports", "squeeze-backports", ["473041FA", "46925553"]),
                                           ("Debian Backports", "wheezy-backports", ["473041FA", "46925553"]),
                                           ]:
                cls._mbd_get_or_create(msglog, origin, codename, keys)

        @classmethod
        def mbd_meta_add_ubuntu(cls, msglog):
            "Add well-known Ubuntu sources"
            for origin, codename, keys in [("Ubuntu", "precise", ["437D05B5", "C0B21F32"]),
                                           ("Ubuntu", "precise-backports/precise", ["437D05B5", "C0B21F32"]),
                                           ("Ubuntu", "quantal", ["437D05B5", "C0B21F32"]),
                                           ("Ubuntu", "quantal-backports/quantal", ["437D05B5", "C0B21F32"]),
                                           ("Ubuntu", "raring", ["437D05B5", "C0B21F32"]),
                                           ("Ubuntu", "raring-backports/raring", ["437D05B5", "C0B21F32"]),
                                           ("Ubuntu", "saucy", ["437D05B5", "C0B21F32"]),
                                           ("Ubuntu", "saucy-backports/saucy", ["437D05B5", "C0B21F32"]),
                                           ]:
                cls._mbd_get_or_create(msglog, origin, codename, keys)

    def mbd_unicode(self):
        """
        .. note:: Workaround for django 1.4.3 bug/new behaviour.

            Since django 1.4.3, accessing 'self.archives.all()'
            does not work anymore: "maximum recursion depth
            exceeded" when trying to add a new source. Seems to
            be a django bug (?). Just don't use it here.
        """
        try:
            archive = self.mbd_get_archive().url
        except:
            archive = None
        return "{o} '{c}' from {a}".format(o=self.origin, c=self.codename, a=archive)

    def mbd_parse_codename(self):
        """
        Return a tuple 'dist, codename' from the codename.

        >>> Source(origin="Debian", codename="squeeze").mbd_parse_codename()
        (u'squeeze', u'squeeze')
        >>> Source(origin="Debian", codename="quantal-backports/quantal").mbd_parse_codename()
        (u'quantal-backports', u'quantal')
        """
        dist, _sep, codename = self.codename.partition("/")
        return dist, codename if codename else dist

    @property
    def mbd_dist(self):
        return self.mbd_parse_codename()[0]

    @property
    def mbd_codename(self):
        return self.mbd_parse_codename()[1]

    def mbd_get_archive(self):
        "Returns the fastest archive."
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
            d=self.mbd_dist,
            c=" ".join([c.name for c in components]))

    def mbd_get_apt_pin(self):
        """
        Apt 'pin line' (for use in a apt 'preference' file).

        'o=' Origin header
        'n=' Codename header
        """
        return "release o={o}, n={c}".format(o=self.origin, c=self.mbd_codename)

    def mbd_prepare(self, request):
        msglog = MsgLog(LOG, request)

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
                        msglog.warn("{o}: Codeversion override active: {r}".format(o=self, r=self.codeversion_override))
                    else:
                        self.codeversion = mini_buildd.misc.guess_codeversion(release)
                        msglog.info("{o}: Codeversion guessed as: {r}".format(o=self, r=self.codeversion))

                    # Set architectures and components (may be auto-added)
                    for a in release["Architectures"].split(" "):
                        new_arch, _created = Architecture.mbd_get_or_create(msglog, name=a)
                        self.architectures.add(new_arch)
                    for c in release["Components"].split(" "):
                        new_component, _created = Component.mbd_get_or_create(msglog, name=c)
                        self.components.add(new_component)
                    msglog.info("{o}: Added archive: {m}".format(o=self, m=m))

                except Exception as e:
                    mini_buildd.setup.log_exception(msglog, "{m}: Not hosting us".format(m=m), e, level=logging.INFO)

        self.mbd_check(request)

    def mbd_sync(self, request):
        self._mbd_remove_and_prepare(request)

    def mbd_remove(self, _request):
        self.archives = []
        self.components = []
        self.architectures = []
        self.description = ""

    def mbd_check(self, _request):
        "Check that this source has at least one working archive left."
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

        @classmethod
        def mbd_meta_add_backports(cls, msglog):
            "Add all backports as prio=1 prio sources"
            for source in Source.objects.filter(codename__regex=r".*-backports"):
                PrioritySource.mbd_get_or_create(msglog, source=source, priority=1)

    def mbd_unicode(self):
        return "{i}: Priority={p}".format(i=self.source, p=self.priority)

    def mbd_get_apt_preferences(self):
        return "Package: *\nPin: {pin}\nPin-Priority: {prio}\n".format(pin=self.source.mbd_get_apt_pin(), prio=self.priority)
