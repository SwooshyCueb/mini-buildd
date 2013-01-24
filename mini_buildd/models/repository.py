# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import contextlib
import shutil
import glob
import re
import socket
import logging

import debian.debian_support

import django.db
import django.core.exceptions
import django.contrib.auth.models

import mini_buildd.setup
import mini_buildd.misc
import mini_buildd.gnupg
import mini_buildd.reprepro

import mini_buildd.models.source
import mini_buildd.models.base

LOG = logging.getLogger(__name__)


class EmailAddress(mini_buildd.models.base.Model):
    address = django.db.models.EmailField(primary_key=True, max_length=255)
    name = django.db.models.CharField(blank=True, max_length=255)

    class Meta(mini_buildd.models.base.Model.Meta):
        verbose_name_plural = "Email addresses"

    class Admin(mini_buildd.models.base.Model.Admin):
        exclude = ("extra_options",)

    def mbd_unicode(self):
        return "{n} <{a}>".format(n=self.name, a=self.address)


class Suite(mini_buildd.models.base.Model):
    name = django.db.models.CharField(
        max_length=100,
        help_text="A suite to support, usually s.th. like 'experimental', 'unstable', 'testing' or 'stable'.")

    class Admin(mini_buildd.models.base.Model.Admin):
        exclude = ("extra_options",)

    def mbd_unicode(self):
        return self.name

    def clean(self, *args, **kwargs):
        self.mbd_validate_regex(r"^[a-z]+$", self.name, "Name")
        super(Suite, self).clean(*args, **kwargs)


class SuiteOption(mini_buildd.models.base.Model):
    layout = django.db.models.ForeignKey("Layout")
    suite = django.db.models.ForeignKey("Suite")

    uploadable = django.db.models.BooleanField(
        default=True,
        help_text="Whether this suite should accept user uploads.")

    experimental = django.db.models.BooleanField(
        default=False,
        help_text="""
Experimental suites must be uploadable and must not
migrate. Also, the packager treats failing extra QA checks (like
lintian) as non-lethal, and will install anyway.
""")

    migrates_to = django.db.models.ForeignKey(
        "self", blank=True, null=True,
        help_text="Give another suite where packages may migrate to (you may need to save this 'blank' first before you see choices here).")

    build_keyring_package = django.db.models.BooleanField(
        default=False,
        help_text="Build keyring package for this suite (i.e., when the resp. Repository action is called).")

    auto_migrate_after = django.db.models.IntegerField(
        default=0,
        help_text="For future use. Automatically migrate packages after x days.")

    not_automatic = django.db.models.BooleanField(
        default=True,
        help_text="Include 'NotAutomatic' in the Release file.")

    but_automatic_upgrades = django.db.models.BooleanField(
        default=True,
        help_text="Include 'ButAutomaticUpgrades' in the Release file.")

    class Meta(mini_buildd.models.base.Model.Meta):
        unique_together = ("suite", "layout")

    def mbd_unicode(self):
        return "{l}: {e}{n}{e} [{u}]{m}".format(
            l=self.layout.name,
            n=self.suite.name,
            e="*" if self.experimental else "",
            u="uploadable" if self.uploadable else "managed",
            m=" => {m}".format(m=self.migrates_to.suite.name) if self.migrates_to else "")

    def clean(self, *args, **kwargs):
        if self.build_keyring_package and not self.uploadable:
            raise django.core.exceptions.ValidationError("You can only build keyring packages on uploadable suites!")
        if self.experimental and self.migrates_to:
            raise django.core.exceptions.ValidationError("Experimental suites may not migrate!")
        if self.experimental and not self.uploadable:
            raise django.core.exceptions.ValidationError("Experimental suites must be uploadable!")
        if self.migrates_to and self.migrates_to.layout != self.layout:
            raise django.core.exceptions.ValidationError("Migrating suites must be in the same layout (you need to save once to make new suites visible).")
        if self.migrates_to and self.migrates_to.uploadable:
            raise django.core.exceptions.ValidationError("You may not migrate to an uploadable suite.")

        super(SuiteOption, self).clean(*args, **kwargs)

    @property
    def rollback(self):
        " Rollback field temporarily implemented as extra_option. "
        return int(self.mbd_get_extra_option("Rollback", "0"))

    def mbd_get_distribution_string(self, repository, distribution, rollback=None):
        dist_string = "{c}-{i}-{s}".format(
            c=distribution.base_source.codename,
            i=repository.identity,
            s=self.suite.name)

        if rollback is None:
            return dist_string
        else:
            if not rollback in range(self.rollback):
                raise Exception("Rollback number out of range: {r} ({m})".format(r=rollback, m=self.rollback))
            return "{d}-rollback{r}".format(d=dist_string, r=rollback)

    def mbd_get_apt_pin(self, repository, distribution):
        return "release n={c}, o={o}".format(
            c=self.mbd_get_distribution_string(repository, distribution),
            o=self.mbd_get_daemon().model.mbd_get_archive_origin())

    def mbd_get_apt_preferences(self, repository, distribution, prio=500):
        return "Package: *\nPin: {pin}\nPin-Priority: {prio}\n".format(
            pin=self.mbd_get_apt_pin(repository, distribution),
            prio=prio)

    def mbd_get_sort_no(self):
        """
        Compute number that may be used to sort suites from 'stable' (0) towards 'experimental'.
        """
        no = 0
        if self.uploadable:
            no += 5
        if self.migrates_to:
            no += 5
        if self.experimental:
            no += 20
        return no


class SuiteOptionInline(django.contrib.admin.TabularInline):
    model = SuiteOption
    extra = 1


class Layout(mini_buildd.models.base.Model):
    name = django.db.models.CharField(primary_key=True, max_length=100)

    suites = django.db.models.ManyToManyField(Suite, through=SuiteOption)

    # Version magic
    default_version = django.db.models.CharField(
        max_length=100, default="~%IDENTITY%%CODEVERSION%+1",
        help_text="""Version string to append to the original version for automated ports; you may use these placeholders:<br/>

%IDENTITY%: Repository identity (see 'Repository').<br/>
%CODEVERSION%: Numerical base distribution version (see 'Source').
""")
    mandatory_version_regex = django.db.models.CharField(
        max_length=100, default=r"~%IDENTITY%%CODEVERSION%\+[1-9]",
        help_text="Mandatory version regex; you may use the same placeholders as for 'default version'.")

    # Version magic (experimental)
    experimental_default_version = django.db.models.CharField(
        max_length=30, default="~%IDENTITY%%CODEVERSION%+0",
        help_text="Like 'default version', but for suites flagged 'experimental'.")

    experimental_mandatory_version_regex = django.db.models.CharField(
        max_length=100, default=r"~%IDENTITY%%CODEVERSION%\+0",
        help_text="Like 'mandatory version', but for suites flagged 'experimental'.")

    class Admin(mini_buildd.models.base.Model.Admin):
        fieldsets = (
            ("Basics", {"fields": ("name",)}),
            ("Version Options", {"classes": ("collapse",),
                                 "fields": ("default_version", "mandatory_version_regex",
                                            "experimental_default_version", "experimental_mandatory_version_regex")}),)
        inlines = (SuiteOptionInline,)

    def mbd_unicode(self):
        return self.name

    @classmethod
    def _mbd_subst_placeholders(cls, value, repository, distribution):
        return mini_buildd.misc.subst_placeholders(
            value,
            {"IDENTITY": repository.identity,
             "CODEVERSION": distribution.base_source.codeversion})

    def mbd_get_mandatory_version_regex(self, repository, distribution, suite_option):
        return self._mbd_subst_placeholders(
            self.experimental_mandatory_version_regex if suite_option.experimental else self.mandatory_version_regex,
            repository, distribution)

    def mbd_get_default_version(self, repository, distribution, suite_option):
        return self._mbd_subst_placeholders(
            self.experimental_default_version if suite_option.experimental else self.default_version,
            repository, distribution)


class ArchitectureOption(mini_buildd.models.base.Model):
    architecture = django.db.models.ForeignKey("Architecture")
    distribution = django.db.models.ForeignKey("Distribution")

    optional = django.db.models.BooleanField(
        default=False,
        help_text="Don't care if the architecture can't be build.")

    build_architecture_all = django.db.models.BooleanField(
        default=False,
        help_text="Use to build arch-all packages.")

    class Meta(mini_buildd.models.base.Model.Meta):
        unique_together = ("architecture", "distribution")

    def clean(self, *args, **kwargs):
        if self.build_architecture_all and self.optional:
            raise django.core.exceptions.ValidationError("Optional architectures must not be architecture all!")
        super(ArchitectureOption, self).clean(*args, **kwargs)


class ArchitectureOptionInline(django.contrib.admin.TabularInline):
    model = ArchitectureOption
    exclude = ("extra_options",)
    extra = 1


class Distribution(mini_buildd.models.base.Model):
    base_source = django.db.models.ForeignKey(mini_buildd.models.source.Source)
    extra_sources = django.db.models.ManyToManyField(mini_buildd.models.source.PrioritySource, blank=True)
    components = django.db.models.ManyToManyField(mini_buildd.models.source.Component)

    architectures = django.db.models.ManyToManyField(mini_buildd.models.source.Architecture, through=ArchitectureOption)

    RESOLVER_APT = 0
    RESOLVER_APTITUDE = 1
    RESOLVER_INTERNAL = 2
    RESOLVER_CHOICES = (
        (RESOLVER_APT, "apt"),
        (RESOLVER_APTITUDE, "aptitude"),
        (RESOLVER_INTERNAL, "internal"))
    build_dep_resolver = django.db.models.IntegerField(choices=RESOLVER_CHOICES, default=RESOLVER_APTITUDE)

    apt_allow_unauthenticated = django.db.models.BooleanField(default=False)

    LINTIAN_DISABLED = 0
    LINTIAN_RUN_ONLY = 1
    LINTIAN_FAIL_ON_ERROR = 2
    LINTIAN_FAIL_ON_WARNING = 3
    LINTIAN_CHOICES = (
        (LINTIAN_DISABLED, "Don't run lintian"),
        (LINTIAN_RUN_ONLY, "Run lintian"),
        (LINTIAN_FAIL_ON_ERROR, "Run lintian and fail on errors"),
        (LINTIAN_FAIL_ON_WARNING, "Run lintian and fail on warnings"))
    lintian_mode = django.db.models.IntegerField(choices=LINTIAN_CHOICES, default=LINTIAN_FAIL_ON_ERROR,
                                                 help_text="""\
Control whether to do lintian checks (via sbuild), and if they
should be prevent package installation (for non-experimental suites).
""")
    lintian_extra_options = django.db.models.CharField(max_length=200, default="--info")

    # piuparts not used atm; placeholder for later
    PIUPARTS_DISABLED = 0
    PIUPARTS_RUN_ONLY = 1
    PIUPARTS_FAIL_ON_ERROR = 2
    PIUPARTS_FAIL_ON_WARNING = 3
    PIUPARTS_CHOICES = (
        (PIUPARTS_DISABLED, "Don't run piuparts"),
        (PIUPARTS_RUN_ONLY, "Run piuparts"),
        (PIUPARTS_FAIL_ON_ERROR, "Run piuparts and fail on errors"),
        (PIUPARTS_FAIL_ON_WARNING, "Run piuparts and fail on warnings"))
    piuparts_mode = django.db.models.IntegerField(choices=PIUPARTS_CHOICES, default=PIUPARTS_DISABLED)
    piuparts_extra_options = django.db.models.CharField(max_length=200, default="--info")
    piuparts_root_arg = django.db.models.CharField(max_length=200, default="sudo")

    chroot_setup_script = django.db.models.TextField(blank=True,
                                                     help_text="""\
Script that will be run via sbuild's '--chroot-setup-command'.
<br/>
Example:
<pre>
#!/bin/sh -e

# Have 'ccache' ready in builds
apt-get --yes --no-install-recommends install ccache

# Use 'eatmydata' in builds; depending on the chroot type, this can speed up builds significantly
apt-get --yes --no-install-recommends install eatmydata

# Accept sun-java6 licence so we can build-depend on it
echo "sun-java6-bin shared/accepted-sun-dlj-v1-1 boolean true" | debconf-set-selections --verbose
echo "sun-java6-jdk shared/accepted-sun-dlj-v1-1 boolean true" | debconf-set-selections --verbose
echo "sun-java6-jre shared/accepted-sun-dlj-v1-1 boolean true" | debconf-set-selections --verbose

# Workaround for Debian Bug #327477 (bash building)
[ -e /dev/fd ] || ln -sv /proc/self/fd /dev/fd
[ -e /dev/stdin ] || ln -sv fd/0 /dev/stdin
[ -e /dev/stdout ] || ln -sv fd/1 /dev/stdout
[ -e /dev/stderr ] || ln -sv fd/2 /dev/stderr
</pre>
""")
    sbuildrc_snippet = django.db.models.TextField(blank=True,
                                                  help_text="""\
Perl snippet to be added in the .sbuildrc for each build.; you may use these placeholders:<br/>
<br/>
%LIBDIR%: Per-chroot persistent dir; may be used for data that should persist beteeen builds (caches, ...).<br/>
<br/>
Example:
<pre>
# Enable ccache
$path = '/usr/lib/ccache:/usr/sbin:/usr/bin:/sbin:/bin:/usr/X11R6/bin:/usr/games';
$build_environment = { 'CCACHE_DIR' => '%LIBDIR%/.ccache' };
</pre>
""")

    class Admin(mini_buildd.models.base.Model.Admin):
        fieldsets = (
            ("Basics", {"fields": ("base_source", "extra_sources", "components")}),
            ("Build options", {"fields": ("build_dep_resolver", "apt_allow_unauthenticated", "lintian_mode", "lintian_extra_options")}),
            ("Extra", {"classes": ("collapse",), "fields": ("chroot_setup_script", "sbuildrc_snippet")}),)
        inlines = (ArchitectureOptionInline,)

    def mbd_unicode(self):
        return "{b} [{c}] [{a}] + ({x})".format(b=self.base_source,
                                                c=" ".join(self.mbd_get_components()),
                                                a=" ".join(self.mbd_get_architectures()),
                                                x=",".join(["{e}".format(e=e) for e in self.extra_sources.all()]))

    def mbd_get_components(self):
        return [c.name for c in sorted(self.components.all(), cmp=mini_buildd.models.source.cmp_components)]

    def mbd_get_architectures(self):
        return [a.architecture.name for a in self.architectureoption_set.all()]

    def mbd_get_archall_architectures(self):
        return [a.architecture.name for a in self.architectureoption_set.all() if a.build_architecture_all]

    def mbd_get_mandatory_architectures(self):
        return [a.architecture.name for a in self.architectureoption_set.all() if not a.optional]

    def mbd_get_apt_line(self, repository, suite_option):
        return "deb {u}{r}/{i}/ {d} {c}".format(
            u=self.mbd_get_daemon().model.mbd_get_http_url(),
            r=os.path.basename(mini_buildd.setup.REPOSITORIES_DIR),
            i=repository.identity,
            d=suite_option.mbd_get_distribution_string(repository, self),
            c=" ".join(self.mbd_get_components()))

    def mbd_get_apt_sources_list(self, repository, suite_option):
        result = "# Base: {p}\n".format(p=self.base_source.mbd_get_apt_pin())
        result += self.base_source.mbd_get_apt_line(self) + "\n\n"
        for e in self.extra_sources.all():
            result += "# Extra: {p}\n".format(p=e.source.mbd_get_apt_pin())
            result += e.source.mbd_get_apt_line(self) + "\n"
            result += "\n"

        result += "# Mini-Buildd: Internal sources\n"
        for s in repository.mbd_get_internal_suite_dependencies(suite_option):
            result += self.mbd_get_apt_line(repository, s) + "\n"

        result += "\n"
        return result

    def mbd_get_apt_preferences(self, repository, suite_option):
        result = ""

        # Get preferences for all extra (prioritized) sources
        for e in self.extra_sources.all():
            result += e.mbd_get_apt_preferences() + "\n"

        # Get preferences for all internal sources
        for s in repository.mbd_get_internal_suite_dependencies(suite_option):
            result += s.mbd_get_apt_preferences(repository, self) + "\n"

        return result

    def mbd_get_sbuildrc_snippet(self, arch):
        libdir = os.path.join(mini_buildd.setup.CHROOTS_DIR, self.base_source.codename, arch, mini_buildd.setup.CHROOT_LIBDIR)
        # Note: For some reason (python, django sqlite, browser?) the text field may be in DOS mode.
        return mini_buildd.misc.fromdos(mini_buildd.misc.subst_placeholders(self.sbuildrc_snippet, {"LIBDIR": libdir}))


class Repository(mini_buildd.models.base.StatusModel):
    identity = django.db.models.CharField(primary_key=True, max_length=50, default=socket.gethostname(),
                                          help_text="""\
The id of the reprepro repository, placed in
'repositories/ID'. It can also be used in 'version enforcement
string' (true for the default layout) -- in this context, it
plays the same role as the well-known 'bpo' version string from
Debian backports.
""")

    layout = django.db.models.ForeignKey(Layout)
    distributions = django.db.models.ManyToManyField(Distribution)

    allow_unauthenticated_uploads = django.db.models.BooleanField(default=False,
                                                                  help_text="Allow unauthenticated user uploads.")

    extra_uploader_keyrings = django.db.models.TextField(blank=True,
                                                         help_text="""\
Extra keyrings, line by line, to be allowed as uploaders (in addition to configured django users).
<br/>
Example:
<pre>
# Allow Debian maintainers (must install the 'debian-keyring' package)
/usr/share/keyrings/debian-keyring.gpg
# Allow from some local keyring file
/etc/my-schlingels.gpg
</pre>
""")

    notify = django.db.models.ManyToManyField(EmailAddress, blank=True,
                                              help_text="Arbitrary list of email addresses to notify.")
    notify_changed_by = django.db.models.BooleanField(default=False,
                                                      help_text="Notify the address in the 'Changed-By' field of the uploaded changes file.")
    notify_maintainer = django.db.models.BooleanField(default=False,
                                                      help_text="Notify the address in the 'Maintainer' field of the uploaded changes file.")

    reprepro_morguedir = django.db.models.BooleanField(default=False,
                                                       help_text="Move files deleted from repo pool to 'morguedir' (see reprepro).")

    external_home_url = django.db.models.URLField(blank=True)

    class Meta(mini_buildd.models.base.StatusModel.Meta):
        verbose_name_plural = "Repositories"

    class Admin(mini_buildd.models.base.StatusModel.Admin):
        fieldsets = (
            ("Basics", {"fields": ("identity", "layout", "distributions", "allow_unauthenticated_uploads", "extra_uploader_keyrings")}),
            ("Notify and extra options", {"fields": ("notify", "notify_changed_by", "notify_maintainer", "reprepro_morguedir", "external_home_url")}),)
        readonly_fields = []

        def get_readonly_fields(self, _request, obj=None):
            "Forbid change identity on existing repository."
            fields = self.readonly_fields
            if obj:
                fields.append("identity")
            return fields

# pylint: disable=R0201
        def action_generate_keyring_packages(self, request, queryset):
            for s in queryset:
                if s.mbd_is_active():
                    s.mbd_generate_keyring_packages(request)
                else:
                    s.mbd_msg_warn(request, "Repository not activated: {r}".format(r=s))
        action_generate_keyring_packages.short_description = "Generate keyring packages"
# pylint: enable=R0201

        actions = [action_generate_keyring_packages]

    def mbd_unicode(self):
        return "{i}: {d}".format(i=self.identity, d=" ".join([d.base_source.codename for d in self.distributions.all()]))

    def clean(self, *args, **kwargs):
        self.mbd_validate_regex(r"^[a-z]+$", self.identity, "Identity")
        super(Repository, self).clean(*args, **kwargs)

    def mbd_generate_keyring_packages(self, request):
        with contextlib.closing(self.mbd_get_daemon().get_keyring_package()) as package:
            for d in self.distributions.all():
                for s in self.layout.suiteoption_set.all().filter(build_keyring_package=True):
                    dist = s.mbd_get_distribution_string(self, d)
                    info = "Keyring port for {d}".format(d=dist)
                    try:
                        self.mbd_get_daemon().portext("file://" + package.dsc, dist)
                        self.mbd_msg_success(request, "Requested: {i}.".format(i=info))
                    except Exception as e:
                        self.mbd_msg_exception(request, "FAILED: {i}".format(i=info), e)

    def mbd_get_uploader_keyring(self):
        gpg = mini_buildd.gnupg.TmpGnuPG()
        # Add keys from django users
        for u in django.contrib.auth.models.User.objects.filter(is_active=True):
            p = u.get_profile()
            if p.mbd_is_active():
                for r in p.may_upload_to.all():
                    if r.identity == self.identity:
                        gpg.add_pub_key(p.key)
                        LOG.info("Uploader key added for '{r}': {k}: {n}".format(r=self, k=p.key_long_id, n=p.key_name))
        # Add configured extra keyrings
        for l in self.extra_uploader_keyrings.splitlines():
            l = l.strip()
            if l and l[0] != "#":
                gpg.add_keyring(l)
                LOG.info("Adding keyring: {k}".format(k=l))
        return gpg

    def mbd_get_path(self):
        return os.path.join(mini_buildd.setup.REPOSITORIES_DIR, self.identity)

    def mbd_get_description(self, distribution, suite_option):
        return "{s} packages for {d}-{i}".format(s=suite_option.suite.name, d=distribution.base_source.codename, i=self.identity)

    def _mbd_find_dist(self, distribution):
        LOG.debug("Finding dist for {d}".format(d=distribution.get()))

        if distribution.repository == self.identity:
            for d in self.distributions.all():
                if d.base_source.codename == distribution.codename:
                    for s in self.layout.suiteoption_set.all():
                        if s.suite.name == distribution.suite:
                            return d, s
        raise Exception("No such distribution in repository {i}: {d}".format(self.identity, d=distribution.get()))

    def mbd_get_apt_keys(self, distribution):
        result = self.mbd_get_daemon().model.mbd_get_pub_key()
        for e in distribution.extra_sources.all():
            for k in e.source.apt_keys.all():
                result += k.key
        return result

    def mbd_get_internal_suite_dependencies(self, suite_option):
        result = []

        # Add ourselfs
        result.append(suite_option)

        if suite_option.experimental:
            # Add all non-experimental suites
            for s in self.layout.suiteoption_set.all().filter(experimental=False):
                result.append(s)
        else:
            # Add all suites that we migrate to
            s = suite_option.migrates_to
            while s:
                result.append(s)
                s = s.migrates_to

        return result

    def _mbd_reprepro_config(self):
        dist_template = """
Codename: {distribution}
Suite: {distribution}
Label: {distribution}
Origin: {origin}
Components: {components}
UDebComponents: {components}
Architectures: source {architectures}
Description: {desc}
SignWith: default
NotAutomatic: {na}
ButAutomaticUpgrades: {bau}
DebIndices: Packages Release . .gz .bz2
DscIndices: Sources Release . .gz .bz2
"""
        result = ""
        for d in self.distributions.all():
            for s in self.layout.suiteoption_set.all():
                result += dist_template.format(
                    distribution=s.mbd_get_distribution_string(self, d),
                    origin=self.mbd_get_daemon().model.mbd_get_archive_origin(),
                    components=" ".join(d.mbd_get_components()),
                    architectures=" ".join([x.name for x in d.architectures.all()]),
                    desc=self.mbd_get_description(d, s),
                    na="yes" if s.not_automatic else "no",
                    bau="yes" if s.but_automatic_upgrades else "no")

                for r in range(s.rollback):
                    result += dist_template.format(
                        distribution=s.mbd_get_distribution_string(self, d, r),
                        origin=self.mbd_get_daemon().model.mbd_get_archive_origin(),
                        components=" ".join(d.mbd_get_components()),
                        architectures=" ".join([x.name for x in d.architectures.all()]),
                        desc="{d}: Automatic rollback distribution #{r}".format(d=self.mbd_get_description(d, s), r=r),
                        na="yes",
                        bau="no")

        return result

    def _mbd_reprepro(self):
        return mini_buildd.reprepro.Reprepro(basedir=self.mbd_get_path())

    def mbd_package_list(self, pattern, typ=None, with_rollbacks=False, dist_regex=""):
        result = []
        for d in self.distributions.all():
            for s in self.layout.suiteoption_set.all():
                rollbacks = s.rollback if with_rollbacks else 0
                for rollback in [None] + range(rollbacks):
                    dist_str = s.mbd_get_distribution_string(self, d, rollback)
                    if re.search(dist_regex, dist_str):
                        result.extend(self._mbd_reprepro().list(pattern, dist_str, typ=typ))
        return result

    def mbd_get_dsc_url(self, distribution, package, version):
        """
        Get complete DSC URL of an installed package.
        """
        subdir = package[:4] if package.startswith("lib") else package[0]

        for c in sorted(distribution.components.all(), cmp=mini_buildd.models.source.cmp_components):
            dsc = "{r}/pool/{c}/{d}/{p}/{p}_{v}.dsc".format(r=self.identity, c=c, d=subdir, p=package, v=version)
            LOG.debug("Checking dsc: {d}".format(d=dsc))
            if os.path.exists(os.path.join(mini_buildd.setup.REPOSITORIES_DIR, dsc)):
                return c, os.path.join(self.mbd_get_daemon().model.mbd_get_http_url(), os.path.basename(mini_buildd.setup.REPOSITORIES_DIR), dsc)

        # Not found in pool
        return None, None

    def mbd_package_show(self, package):
        """
        Result is of the form:

        [(CODENAME, [{"distribution": DIST,
                      "component": COMPONENT,
                      "source": PKG_NAME,
                      "sourceversion": VERSION,
                      "migrates_to": DIST,
                      "uploadable": BOOL,
                      "experimental": BOOL,
                      "sort_no": NO,
                      "rollbacks": [{"no": 0, "distribution": DIST, "source": PKG_NAME, "sourceversion": VERS0}, ...]}])]
        """
        result = []

        def get_or_create_codename(codename):
            for p in result:
                if p[0] == codename:
                    return p[1]
            new = []
            result.append((codename, new))
            LOG.debug("Codename pair created: {c}".format(c=codename))
            return new

        def get_or_create_distribution(codename, distribution, component):
            for p in codename:
                if p["distribution"] == distribution and (not component or component == p["component"]):
                    return p
            new = {}
            codename.append(new)
            LOG.debug("Distribution dict created: {d}".format(d=distribution))
            return new

        pkg_show = self._mbd_reprepro().show(package)

        # Init all codenames
        for r in pkg_show:
            dist = mini_buildd.misc.Distribution(r["distribution"])
            distribution, suite = self._mbd_find_dist(dist)

            # Get list of dicts with unique distributions
            codename = get_or_create_codename(dist.codename)

            # Get component and URL early
            component, dsc_url = self.mbd_get_dsc_url(distribution, r["source"], r["sourceversion"])

            # Get dict with distribution values
            values = get_or_create_distribution(codename, dist.get(rollback=False), component)

            # Always set valid default values (in case of rollback version w/o a version in actual dists, or if the rollback comes first)
            values.setdefault("distribution", dist.get(rollback=False))
            values.setdefault("component", component)
            values.setdefault("source", "")
            values.setdefault("sourceversion", "")
            values.setdefault("dsc_url", "")
            values.setdefault("migrates_to", suite.migrates_to.mbd_get_distribution_string(self, distribution) if suite.migrates_to else "")
            values.setdefault("uploadable", suite.uploadable)
            values.setdefault("experimental", suite.experimental)
            values.setdefault("sort_no", suite.mbd_get_sort_no())
            values.setdefault("rollback", suite.rollback)
            values.setdefault("rollbacks", [])

            if dist.is_rollback:
                # Add to rollback list with "no" appended
                r["no"] = dist.rollback_no
                r["component"] = component
                r["dsc_url"] = dsc_url
                values["rollbacks"].append(r)
            else:
                # Copy all reprepro values
                for k, v in r.items():
                    values[k] = v

                # Extra: URL, is_migrated flag
                values["dsc_url"] = dsc_url
                values["is_migrated"] = \
                    values["migrates_to"] and \
                    self._mbd_package_find(pkg_show, distribution=values["migrates_to"], version=values["sourceversion"])

        return result

    @classmethod
    def _mbd_package_find(cls, pkg_show, distribution=None, version=None):
        for r in pkg_show:
            if not distribution or r["distribution"] == distribution:
                if not version or r["sourceversion"] == version:
                    return r

    def mbd_package_find(self, package, distribution=None, version=None):
        return self._mbd_package_find(self._mbd_reprepro().show(package), distribution, version)

    def _mbd_package_shift_rollbacks(self, distribution, suite_option, package_name):
        for r in range(suite_option.rollback - 1, -1, -1):
            src = suite_option.mbd_get_distribution_string(self, distribution, None if r == 0 else r - 1)
            dst = suite_option.mbd_get_distribution_string(self, distribution, r)
            LOG.info("Rollback: Moving {p}: {s} to {d}".format(p=package_name, s=src, d=dst))
            try:
                self._mbd_reprepro().migrate(package_name, src, dst)
            except Exception as e:
                mini_buildd.setup.log_exception(LOG, "Rollback failed (ignoring)", e)

    def mbd_package_migrate(self, package, distribution, suite, rollback=None, version=None):
        src_dist = suite.mbd_get_distribution_string(self, distribution)
        pkg_show = self._mbd_reprepro().show(package)

        if rollback is not None:
            LOG.info("Rollback restore of '{p}' from rollback {r} to '{d}'".format(p=package, r=rollback, d=src_dist))
            if self._mbd_package_find(pkg_show, distribution=src_dist, version=version):
                raise Exception("Package '{p}' exists in '{d}': Remove first to restore rollback".format(p=package, d=src_dist))

            rob_dist = suite.mbd_get_distribution_string(self, distribution, rollback=rollback)
            if not self._mbd_package_find(pkg_show, distribution=rob_dist):
                raise Exception("Package '{p}' has no rollback '{r}'".format(p=package, r=rollback))

            # Actually migrate package in reprepro
            return self._mbd_reprepro().migrate(package, rob_dist, src_dist, version)

        # Get src and dst dist strings, and check we are configured to migrate
        if not suite.migrates_to:
            raise Exception("You can't migrate from '{d}'".format(d=src_dist))
        dst_dist = suite.migrates_to.mbd_get_distribution_string(self, distribution)

        # Check if package is in src_dst
        src_pkg = self._mbd_package_find(pkg_show, distribution=src_dist)
        if src_pkg is None:
            raise Exception("Package '{p}' not in '{d}'".format(p=package, d=src_dist))
        # Check that version is not already migrated
        dst_pkg = self._mbd_package_find(pkg_show, distribution=dst_dist)
        if dst_pkg is not None and src_pkg["sourceversion"] == dst_pkg["sourceversion"]:
            raise Exception("Version '{v}' already migrated to '{d}'".format(v=src_pkg["sourceversion"], d=dst_dist))

        # Shift rollbacks in the destination distributions
        if dst_pkg is not None:
            self._mbd_package_shift_rollbacks(distribution, suite.migrates_to, package)

        # Actually migrate package in reprepro
        return self._mbd_reprepro().migrate(package, src_dist, dst_dist, version)

    def mbd_package_remove(self, package, distribution, suite, rollback=None, version=None):
        dist_str = suite.mbd_get_distribution_string(self, distribution, rollback)
        if not self.mbd_package_find(package, distribution=dist_str):
            raise Exception("Package '{p}' not in '{d}'".format(p=package, d=dist_str))

        if rollback is None:
            # Shift rollbacks
            self._mbd_package_shift_rollbacks(distribution, suite, package)
            # Remove package
            return self._mbd_reprepro().remove(package, dist_str, version)
        else:
            # Rollback removal
            res = self._mbd_reprepro().remove(package, dist_str, version)

            # Fix up empty rollback dist
            for r in range(rollback, suite.rollback - 1):
                src = suite.mbd_get_distribution_string(self, distribution, r + 1)
                dst = suite.mbd_get_distribution_string(self, distribution, r)
                try:
                    res += self._mbd_reprepro().migrate(package, src, dst)
                    res += self._mbd_reprepro().remove(package, src)
                except Exception as e:
                    inf = "Rollback: Moving '{p}' from '{s}' to '{d}' FAILED (ignoring)".format(p=package, s=src, d=dst)
                    mini_buildd.setup.log_exception(LOG, inf, e, logging.WARN)
                    res += "WARNING: {i}: {e}\n".format(i=inf, e=e)
            return res

    def mbd_package_precheck(self, distribution, suite_option, package, version):
        # 1st, check that the given version matches the distribution's version restrictions
        mandatory_regex = self.layout.mbd_get_mandatory_version_regex(self, distribution, suite_option)
        if not re.compile(mandatory_regex).search(version):
            raise Exception("Version restrictions failed for suite '{s}': '{m}' not in '{v}'".format(s=suite_option.suite.name,
                                                                                                     m=mandatory_regex,
                                                                                                     v=version))

        pkg_show = self._mbd_reprepro().show(package)
        dist_str = suite_option.mbd_get_distribution_string(self, distribution)

        # 2nd: Check whether the very same version is already in any distribution
        pkg_version_in_repo = self._mbd_package_find(pkg_show, version=version)
        if pkg_version_in_repo:
            raise Exception("Package '{p}' with same version '{v}' already installed in '{d}'".format(p=package,
                                                                                                      v=version,
                                                                                                      d=pkg_version_in_repo["distribution"]))

        # 3rd: Check that distribution's current version is smaller than the to-be installed version
        pkg_in_dist = self._mbd_package_find(pkg_show, distribution=dist_str)
        if pkg_in_dist and debian.debian_support.Version(version) < debian.debian_support.Version(pkg_in_dist["sourceversion"]):
            raise Exception("Package '{p}' has greater version '{v}' installed in '{d}'".format(p=package,
                                                                                                v=pkg_in_dist["sourceversion"],
                                                                                                d=dist_str))

    def _mbd_package_install(self, bres):
        with contextlib.closing(mini_buildd.misc.TmpDir()) as t:
            bres.untar(path=t.tmpdir)
            self._mbd_reprepro().install(" ".join(glob.glob(os.path.join(t.tmpdir, "*.changes"))),
                                         bres["Distribution"])
            LOG.info("Installed: {p} ({d})".format(p=bres.get_pkg_id(with_arch=True), d=bres["Distribution"]))

    def mbd_package_install(self, distribution, suite_option, bresults):
        """
        Install a dict arch:bres of successful build results.
        """
        # Get the full distribution str
        dist_str = suite_option.mbd_get_distribution_string(self, distribution)

        # Get the 'archall' arch
        archall = distribution.mbd_get_archall_architectures()[0]
        LOG.debug("Package install: Archall={a}".format(a=archall))

        # Check that all mandatory archs are present
        missing_mandatory_archs = [arch for arch in distribution.mbd_get_mandatory_architectures() if arch not in bresults]
        if missing_mandatory_archs:
            raise Exception("{n} mandatory architecture(s) missing: {a}".format(n=len(missing_mandatory_archs), a=" ".join(missing_mandatory_archs)))

        # Get the (source) package name
        package = bresults[archall]["Source"]
        LOG.debug("Package install: Package={p}".format(p=package))

        # Shift current package up in the rollback distributions (unless this is the initial install)
        if self.mbd_package_find(package, distribution=dist_str):
            self._mbd_package_shift_rollbacks(distribution, suite_option, package)

        # First, install the archall arch, so we fail early in case there are problems with the uploaded dsc.
        self._mbd_package_install(bresults[archall])

        # Second, install all other archs
        for bres in [s for a, s in bresults.items() if a != archall]:
            # Don't try install if skipped
            if bres.get("Sbuild-Status") == "skipped":
                LOG.info("Skipped: {p} ({d})".format(p=bres.get_pkg_id(with_arch=True), d=bres["Distribution"]))
            else:
                self._mbd_package_install(bres)

    def mbd_prepare(self, _request):
        """
        Idempotent repository preparation. This may be used as-is as mbd_check.
        """
        # Architecture sanity checks
        for d in self.distributions.all():
            if not d.architectureoption_set.all().filter(optional=False):
                raise Exception("{d}: There must be at least one mandatory architecture!".format(d=d))
            if len(d.architectureoption_set.all().filter(optional=False, build_architecture_all=True)) != 1:
                raise Exception("{d}: There must be exactly one one arch-all architecture!".format(d=d))

        # Check that the codenames of the distribution are unique
        codenames = []
        for d in self.distributions.all():
            if d.base_source.codename in codenames:
                raise django.core.exceptions.ValidationError("Multiple distribution codename in: {d}".format(d=d))
            codenames.append(d.base_source.codename)

            # Check for mandatory component "main"
            if not d.components.all().filter(name="main"):
                raise django.core.exceptions.ValidationError("Mandatory component 'main' missing in: {d}".format(d=d))

        # (Re-)build config files
        mini_buildd.misc.mkdirs(os.path.join(self.mbd_get_path(), "conf"))
        mini_buildd.misc.ConfFile(
            os.path.join(self.mbd_get_path(), "conf", "distributions"),
            self._mbd_reprepro_config()).save()
        mini_buildd.misc.ConfFile(
            os.path.join(self.mbd_get_path(), "conf", "options"),
            """\
gnupghome {h}
{m}
""".format(h=os.path.join(mini_buildd.setup.HOME_DIR, ".gnupg"), m="morguedir +b/morguedir" if self.reprepro_morguedir else "")).save()

        # (Re-)index
        self._mbd_reprepro().reindex()

    def mbd_unprepare(self, _request):
        if os.path.exists(self.mbd_get_path()):
            shutil.rmtree(self.mbd_get_path())

    def mbd_check(self, request):
        self.mbd_prepare(request)

    def mbd_get_status_dependencies(self):
        result = []
        for d in self.distributions.all():
            result.append(d.base_source)
            for e in d.extra_sources.all():
                result.append(e.source)
        return result
