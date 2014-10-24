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
            for url in ["http://archive.ubuntu.com/ubuntu/",              # Ubuntu releases
                        "http://old-releases.ubuntu.com/ubuntu/",         # Older Ubuntu release
                        ]:
                cls._mbd_get_or_create(msglog, url)
            msglog.info("Consider replacing these archives with you closest mirror(s); check netselect-apt.")

    def __unicode__(self):
        return "{u} (ping {p} ms)".format(u=self.url, p=self.ping)

    def clean(self, *args, **kwargs):
        if self.url[-1] != "/" or self.url[-2] == "/":
            raise django.core.exceptions.ValidationError("The URL must have exactly one trailing slash (like 'http://example.org/path/').")
        super(Archive, self).clean(*args, **kwargs)

    def mbd_get_matching_release(self, request, source, gnupg):
        url = "{u}/dists/{d}/Release".format(u=self.url, d=source.codename)
        with tempfile.NamedTemporaryFile() as release_file:
            MsgLog(LOG, request).debug("Downloading '{u}' to '{t}'".format(u=url, t=release_file.name))
            try:
                release_file.write(urllib2.urlopen(url).read())
            except urllib2.HTTPError as e:
                if e.code == 404:
                    MsgLog(LOG, request).debug("{a}: '404 Not Found' on '{u}'".format(a=self, u=url))
                    # Not for us
                    return None
                raise
            release_file.flush()
            release_file.seek(0)
            release = debian.deb822.Release(release_file)

            # Check release file fields
            if not source.mbd_is_matching_release(request, release):
                return None

            # Check signature
            with tempfile.NamedTemporaryFile() as signature:
                MsgLog(LOG, request).debug("Downloading '{u}.gpg' to '{t}'".format(u=url, t=signature.name))
                signature.write(urllib2.urlopen(url + ".gpg").read())
                signature.flush()
                gnupg.verify(signature.name, release_file.name)

            # Ok, this is for this source
            return release

    def mbd_ping(self, request):
        "Ping and update the ping value."
        try:
            t0 = datetime.datetime.now()
            # Append dists to URL for ping check: Archive may be
            # just fine, but not allow to access to base URL
            # (like ourselves ;). Any archive _must_ have dists/ anyway.
            try:
                urllib2.urlopen("{u}/dists/".format(u=self.url))
            except urllib2.HTTPError as e:
                # Allow HTTP 4xx client errors through; these might be valid use cases like:
                # 404 Usage Information: apt-cacher-ng
                if not 400 <= e.code <= 499:
                    raise

            delta = datetime.datetime.now() - t0
            self.ping = mini_buildd.misc.timedelta_total_seconds(delta) * (10 ** 3)
            self.save()
            MsgLog(LOG, request).debug("{s}: Ping!".format(s=self))
        except Exception as e:
            self.ping = -1.0
            self.save()
            raise Exception("{s}: Does not ping: {e}".format(s=self, e=e))

    def mbd_get_reverse_dependencies(self):
        "Return all sources (and their deps) that use us."
        result = [s for s in self.source_set.all()]
        for s in self.source_set.all():
            result += s.mbd_get_reverse_dependencies()
        return result


class Architecture(mini_buildd.models.base.Model):
    name = django.db.models.CharField(primary_key=True, max_length=50)

    def __unicode__(self):
        return self.name

    @classmethod
    def mbd_host_architecture(cls):
        return mini_buildd.misc.sose_call(["dpkg", "--print-architecture"]).strip()

    @classmethod
    def mbd_supported_architectures(cls, arch=None):
        "Some archs also natively support other archs."
        arch = arch or cls.mbd_host_architecture()
        arch_map = {"amd64": ["i386"]}
        return [arch] + arch_map.get(arch, [])


class Component(mini_buildd.models.base.Model):
    name = django.db.models.CharField(primary_key=True, max_length=50)

    def __unicode__(self):
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
The name of the directory below 'dists/' in archives this source refers to; this is also used
as-is to check the 'Codename' field in the Release file (unless you overwrite it in
extra options, see below).
<br />
The <b>extra options</b> below may be used to
<em>overwrite the Codename</em> to check in the Release file in case it differs or
<em>put more fields to check</em> with the Release file to anonymously identify the source and/or to get
the source's pinning right.
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
        help_text="""
Save this as empty string to have the codeversion re-guessed on check, or
put your own override value here if the guessed string is broken. The
codeversion is only used for base sources.""")
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
            ("Identity", {"fields": ("origin", "codename", "extra_options", "apt_keys")}),
            ("Extra", {"classes": ("collapse",), "fields": ("description", "codeversion", "codeversion_override", "archives", "components", "architectures")}),)
        filter_horizontal = ("apt_keys",)

        def get_readonly_fields(self, _request, obj=None):
            "Forbid to change identity on existing source (usually a bad idea; repos/chroots that refer to us may break)."
            fields = copy.copy(self.readonly_fields)
            if obj:
                fields.append("origin")
                fields.append("codename")
            return fields

        @classmethod
        def _mbd_get_or_create(cls, msglog, origin, codename, keys, extra_options=""):
            try:
                obj, created = Source.mbd_get_or_create(msglog, origin=origin, codename=codename, extra_options=extra_options)
                if created:
                    for long_key_id in keys:
                        matching_keys = mini_buildd.models.gnupg.AptKey.mbd_filter_key(long_key_id)
                        if matching_keys:
                            apt_key = matching_keys[0]
                            msglog.debug("Already exists: {k}".format(k=apt_key))
                        else:
                            apt_key, _created = mini_buildd.models.gnupg.AptKey.mbd_get_or_create(msglog, key_id=long_key_id)
                        obj.apt_keys.add(apt_key)
                    obj.save()
            except Exception as e:
                msglog.debug("Can't add {c} (most likely a non-default instance already exists): {e}".format(c=codename, e=e))

        @classmethod
        def mbd_meta_add_debian(cls, msglog):
            """
            Add well-known Debian sources

            8B48AD6246925553: Debian Archive Automatic Signing Key (7.0/wheezy) <ftpmaster@debian.org>
            6FB2A1C265FFB764: Wheezy Stable Release Key <debian-release@lists.debian.org>

            AED4B06F473041FA: Debian Archive Automatic Signing Key (6.0/squeeze) <ftpmaster@debian.org>
            64481591B98321F9: Squeeze Stable Release Key <debian-release@lists.debian.org>

            9AA38DCD55BE302B: Debian Archive Automatic Signing Key (5.0/lenny) <ftpmaster@debian.org>
            4D270D06F42584E6: Lenny Stable Release Key <debian-release@lists.debian.org>

            B5D0C804ADB11277: Etch Stable Release Key <debian-release@lists.debian.org>
            EA8E8B2116BA136C: Backports.org Archive Key <ftp-master@backports.org>
            """
            cls._mbd_get_or_create(msglog, "Debian", "etch",
                                   ["9AA38DCD55BE302B", "B5D0C804ADB11277"])
            cls._mbd_get_or_create(msglog, "Debian", "lenny",
                                   ["AED4B06F473041FA", "4D270D06F42584E6"])
            cls._mbd_get_or_create(msglog, "Debian", "squeeze",
                                   ["AED4B06F473041FA", "64481591B98321F9"])
            cls._mbd_get_or_create(msglog, "Debian", "wheezy",
                                   ["8B48AD6246925553", "6FB2A1C265FFB764"])
            cls._mbd_get_or_create(msglog, "Debian", "jessie",
                                   ["8B48AD6246925553", "6FB2A1C265FFB764"])
            cls._mbd_get_or_create(msglog, "Debian", "sid",
                                   ["8B48AD6246925553", "6FB2A1C265FFB764"])
            cls._mbd_get_or_create(msglog, "Backports.org archive", "etch-backports",
                                   ["EA8E8B2116BA136C"])
            cls._mbd_get_or_create(msglog, "Debian Backports", "lenny-backports",
                                   ["AED4B06F473041FA"])
            cls._mbd_get_or_create(msglog, "Debian Backports", "squeeze-backports",
                                   ["AED4B06F473041FA", "8B48AD6246925553"])
            cls._mbd_get_or_create(msglog, "Debian Backports", "wheezy-backports",
                                   ["8B48AD6246925553", "6FB2A1C265FFB764"])

        @classmethod
        def mbd_meta_add_ubuntu(cls, msglog):
            "Add well-known Ubuntu sources"
            cls._mbd_get_or_create(msglog, "Ubuntu", "precise",
                                   ["40976EAF437D05B5", "3B4FE6ACC0B21F32"])
            cls._mbd_get_or_create(msglog, "Ubuntu", "precise-backports",
                                   ["40976EAF437D05B5", "3B4FE6ACC0B21F32"],
                                   "Codename: precise\nSuite: precise-backports")
            cls._mbd_get_or_create(msglog, "Ubuntu", "quantal",
                                   ["40976EAF437D05B5", "3B4FE6ACC0B21F32"])
            cls._mbd_get_or_create(msglog, "Ubuntu", "quantal-backports",
                                   ["40976EAF437D05B5", "3B4FE6ACC0B21F32"],
                                   "Codename: quantal\nSuite: quantal-backports")
            cls._mbd_get_or_create(msglog, "Ubuntu", "raring",
                                   ["40976EAF437D05B5", "3B4FE6ACC0B21F32"])
            cls._mbd_get_or_create(msglog, "Ubuntu", "raring-backports",
                                   ["40976EAF437D05B5", "3B4FE6ACC0B21F32"],
                                   "Codename: raring\nSuite: raring-backports")
            cls._mbd_get_or_create(msglog, "Ubuntu", "saucy",
                                   ["40976EAF437D05B5", "3B4FE6ACC0B21F32"])
            cls._mbd_get_or_create(msglog, "Ubuntu", "saucy-backports",
                                   ["40976EAF437D05B5", "3B4FE6ACC0B21F32"],
                                   "Codename: saucy\nSuite: saucy-backports")
            cls._mbd_get_or_create(msglog, "Ubuntu", "trusty",
                                   ["40976EAF437D05B5", "3B4FE6ACC0B21F32"])
            cls._mbd_get_or_create(msglog, "Ubuntu", "trusty-backports",
                                   ["40976EAF437D05B5", "3B4FE6ACC0B21F32"],
                                   "Codename: trusty\nSuite: trusty-backports")
            cls._mbd_get_or_create(msglog, "Ubuntu", "utopic",
                                   ["40976EAF437D05B5", "3B4FE6ACC0B21F32"])
            cls._mbd_get_or_create(msglog, "Ubuntu", "utopic-backports",
                                   ["40976EAF437D05B5", "3B4FE6ACC0B21F32"],
                                   "Codename: utopic\nSuite: utopic-backports")

        @classmethod
        def mbd_filter_active_base_sources(cls):
            "Filter active base sources; needed in chroot and distribution wizards."
            return Source.objects.filter(status__gte=Source.STATUS_ACTIVE,
                                         origin__in=["Debian", "Ubuntu"],
                                         codename__regex=r"^[a-z]+$")

    def __unicode__(self):
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
        return "{o} '{c}' from '{a}'".format(o=self.origin, c=self.codename, a=archive)

    def mbd_release_file_values(self):
        "Compute a dict of values a matching release file must have."
        values = self.mbd_get_extra_options()

        # Set Origin and Codename (may be overwritten) from fields
        values["Origin"] = self.origin
        if not values.get("Codename"):
            values["Codename"] = self.codename

        return values

    def mbd_is_matching_release(self, request, release):
        "Check that this release file matches us."
        for key, value in self.mbd_release_file_values().items():
            # Check identity: origin, codename
            MsgLog(LOG, request).debug("Checking '{k}: {v}'".format(k=key, v=value))
            if value != release[key]:
                MsgLog(LOG, request).debug("Release[{k}] field mismatch: '{rv}', expected '{v}'.".format(k=key, rv=release[key], v=value))
                return False
        return True

    def mbd_get_archive(self):
        "Returns the fastest archive."
        oa_list = self.archives.all().filter(ping__gte=0.0).order_by("ping")
        if oa_list:
            return oa_list[0]
        else:
            raise Exception("{s}: No archive found. Please add appropriate archive and/or check network setup.".format(s=self))

    def mbd_get_apt_line(self, distribution, prefix="deb "):
        allowed_components = [c.name for c in distribution.components.all()]
        components = sorted([c for c in self.components.all() if c.name in allowed_components], cmp=cmp_components)
        return "{p}{u} {d} {c}".format(
            p=prefix,
            u=self.mbd_get_archive().url,
            d=self.codename + ("" if components else "/"),
            c=" ".join([c.name for c in components]))

    def mbd_get_apt_pin(self):
        "Apt 'pin line' (for use in a apt 'preference' file)."
        # See man apt_preferences for the field/pin mapping
        supported_fields = {"Origin": "o", "Codename": "n", "Suite": "a", "Archive": "a", "Version": "v", "Label": "l"}
        pins = []
        for key, value in self.mbd_release_file_values().items():
            k = supported_fields.get(key)
            if k:
                pins.append("{k}={v}".format(k=k, v=value))
        return "release " + ", ".join(pins)

    def mbd_prepare(self, request):
        if not self.apt_keys.all():
            raise Exception("{s}: Please add apt keys to this source.".format(s=self))
        if self.mbd_get_extra_option("Origin"):
            raise Exception("{s}: You may not override 'Origin', just use the origin field.".format(s=self))
        MsgLog(LOG, request).info("{s} with pin: {p}".format(s=self, p=self.mbd_get_apt_pin()))

    def mbd_sync(self, request):
        self._mbd_remove_and_prepare(request)

    def mbd_remove(self, _request):
        self.archives = []
        self.components = []
        self.architectures = []
        self.description = ""

    def mbd_check(self, request):
        "Rescan all archives, and check that there is at least one working."
        msglog = MsgLog(LOG, request)

        self.archives = []
        with contextlib.closing(mini_buildd.gnupg.TmpGnuPG()) as gpg:
            for k in self.apt_keys.all():
                gpg.add_pub_key(k.key)

            for archive in Archive.objects.all():
                try:
                    # Check and update the ping value
                    archive.mbd_ping(request)

                    # Get release if this archive serves us, else exception
                    release = archive.mbd_get_matching_release(request, self, gpg)
                    if release:
                        # Implicitely save ping value for this archive
                        self.archives.add(archive)
                        self.description = release["Description"]

                        # Set codeversion
                        self.codeversion = ""
                        if self.codeversion_override:
                            self.codeversion = self.codeversion_override
                            msglog.info("{o}: Codeversion override active: {r}".format(o=self, r=self.codeversion_override))
                        else:
                            self.codeversion = mini_buildd.misc.guess_codeversion(release)
                            self.codeversion_override = self.codeversion
                            msglog.info("{o}: Codeversion guessed as: {r}".format(o=self, r=self.codeversion))

                        # Set architectures and components (may be auto-added)
                        if release.get("Architectures"):
                            for a in release["Architectures"].split(" "):
                                new_arch, _created = Architecture.mbd_get_or_create(msglog, name=a)
                                self.architectures.add(new_arch)
                        if release.get("Components"):
                            for c in release["Components"].split(" "):
                                new_component, _created = Component.mbd_get_or_create(msglog, name=c)
                                self.components.add(new_component)
                        msglog.info("{o}: Added archive: {a}".format(o=self, a=archive))
                    else:
                        msglog.debug("{a}: Not hosting {s}".format(a=archive, s=self))
                except Exception as e:
                    mini_buildd.setup.log_exception(msglog, "Error checking {a} for {s} (check Archive or Source)".format(a=archive, s=self), e)

        # Check that at least one archive can be found
        self.mbd_get_archive()

    def mbd_get_dependencies(self):
        return self.apt_keys.all()

    def mbd_get_reverse_dependencies(self):
        "Return all chroots and repositories that use us."
        result = [c for c in self.chroot_set.all()]
        for d in self.distribution_set.all():
            result += d.mbd_get_reverse_dependencies()
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
        def mbd_meta_add_extras(cls, msglog):
            "Add all backports as prio=1 prio sources"
            for source in Source.objects.exclude(codename__regex=r"^[a-z]+$"):
                PrioritySource.mbd_get_or_create(msglog, source=source, priority=1)

    def __unicode__(self):
        return "{i} with prio={p}".format(i=self.source, p=self.priority)

    def mbd_get_apt_preferences(self):
        return "Package: *\nPin: {pin}\nPin-Priority: {prio}\n".format(pin=self.source.mbd_get_apt_pin(), prio=self.priority)
