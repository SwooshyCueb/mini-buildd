# -*- coding: utf-8 -*-
# django false-positives:
# pylint: disable=E1123,E1120
from __future__ import unicode_literals

import os
import copy
import contextlib
import shutil
import glob
import re
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

from mini_buildd.models.msglog import MsgLog
LOG = logging.getLogger(__name__)


class EmailAddress(mini_buildd.models.base.Model):
    address = django.db.models.EmailField(primary_key=True, max_length=255)
    name = django.db.models.CharField(blank=True, max_length=255)

    class Meta(mini_buildd.models.base.Model.Meta):
        verbose_name_plural = "Email addresses"

    class Admin(mini_buildd.models.base.Model.Admin):
        exclude = ("extra_options",)

    def __unicode__(self):
        return "{n} <{a}>".format(n=self.name, a=self.address)


class Suite(mini_buildd.models.base.Model):
    name = django.db.models.CharField(
        max_length=100,
        help_text="A suite to support, usually s.th. like 'experimental', 'unstable', 'testing' or 'stable'.")

    class Admin(mini_buildd.models.base.Model.Admin):
        exclude = ("extra_options",)

    def __unicode__(self):
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

    def __unicode__(self):
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
            if rollback not in range(self.rollback):
                raise Exception("Rollback number out of range: {r} ({m})".format(r=rollback, m=self.rollback))
            return "{d}-rollback{r}".format(d=dist_string, r=rollback)

    def mbd_get_apt_pin(self, repository, distribution):
        return "release n={c}, o={o}".format(
            c=self.mbd_get_distribution_string(repository, distribution),
            o=self.mbd_get_daemon().model.mbd_get_archive_origin())

    def mbd_get_apt_preferences(self, repository, distribution, prio=1):
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
        help_text="""Version string to append to the original version for automated ports; you may use these placeholders:<br />

%IDENTITY%: Repository identity (see 'Repository').<br />
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
                                            "experimental_default_version", "experimental_mandatory_version_regex")}),
            ("Extra Options", {"classes": ("collapse",),
                               "description": """
<b>Supported extra options</b>
<p><em>Meta-Distributions: META=CODENAME-SUITE[ META=CODENAME-SUITE[...</em>: Support METAs alone as distribution identifier.</p>
<p>
Meta distribution identifiers should be unique across all
repositories; usually, a layout with meta distributions should
only be used by at most one repository.
</p>
<p>
<em>Example</em>:
<tt>Meta-Distributions: unstable=sid-unstable experimental=sid-experimental</tt>
(see standard layout 'Debian Developer'), to allow upload/testing of
packages (to unstable,experimental,..) aimed for Debian.
</p>
""",
                               "fields": ("extra_options",)}),)
        inlines = (SuiteOptionInline,)

        @classmethod
        def mbd_meta_create_defaults(cls, msglog):
            "Create default layouts and suites."
            stable, created = Suite.mbd_get_or_create(msglog, name="stable")
            testing, created = Suite.mbd_get_or_create(msglog, name="testing")
            unstable, created = Suite.mbd_get_or_create(msglog, name="unstable")
            snapshot, created = Suite.mbd_get_or_create(msglog, name="snapshot")
            experimental, created = Suite.mbd_get_or_create(msglog, name="experimental")

            for name, extra_options in {"Default": {"stable": "Rollback: 6\n",
                                                    "testing": "Rollback: 3\n",
                                                    "unstable": "Rollback: 9\n",
                                                    "snapshot": "Rollback: 12\n",
                                                    "experimental": "Rollback: 6\n"},
                                        "Default (no rollbacks)": {}}.items():

                default_layout, created = Layout.mbd_get_or_create(msglog, name=name)
                if created:
                    so_stable = SuiteOption(
                        layout=default_layout,
                        suite=stable,
                        uploadable=False,
                        extra_options=extra_options.get("stable", ""))
                    so_stable.save()

                    so_testing = SuiteOption(
                        layout=default_layout,
                        suite=testing,
                        uploadable=False,
                        migrates_to=so_stable,
                        extra_options=extra_options.get("testing", ""))
                    so_testing.save()

                    so_unstable = SuiteOption(
                        layout=default_layout,
                        suite=unstable,
                        migrates_to=so_testing,
                        build_keyring_package=True,
                        extra_options=extra_options.get("unstable", ""))
                    so_unstable.save()

                    so_snapshot = SuiteOption(
                        layout=default_layout,
                        suite=snapshot,
                        experimental=True,
                        extra_options=extra_options.get("snapshot", ""))
                    so_snapshot.save()

                    so_experimental = SuiteOption(
                        layout=default_layout,
                        suite=experimental,
                        experimental=True,
                        but_automatic_upgrades=False,
                        extra_options=extra_options.get("experimental", ""))
                    so_experimental.save()

            # Debian Developer layout
            debdev_layout, created = Layout.mbd_get_or_create(
                msglog,
                name="Debian Developer",
                defaults={"mandatory_version_regex": ".*",
                          "experimental_mandatory_version_regex": ".*",
                          "extra_options": "Meta-Distributions: stable=squeeze-unstable unstable=sid-unstable experimental=sid-experimental\n"})

            if created:
                debdev_unstable = SuiteOption(
                    layout=debdev_layout,
                    suite=unstable,
                    build_keyring_package=True)
                debdev_unstable.save()

                debdev_experimental = SuiteOption(
                    layout=debdev_layout,
                    suite=experimental,
                    uploadable=True,
                    experimental=True,
                    but_automatic_upgrades=False)
                debdev_experimental.save()

    def __unicode__(self):
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

    def mbd_get_reverse_dependencies(self):
        "When the layout changes, all repos that use that layout also change."
        return [r for r in self.repository_set.all()]


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

    def __unicode__(self):
        return "{a} for {d}".format(a=self.architecture, d=self.distribution)

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
should prevent package installation (for non-experimental suites).
<p>
<b>IMPORTANT</b>: Note that for Distributions based on lenny or older,
there is no way to suppress the 'bad distribution' check, which
will always result in a lintian error. So all such Distributions
must have lintian disabled or -- recommended -- set to 'run
only'. This way, lintian is still run and you can look it up in
the build logs.
</p>
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
                                                     default="""\
#!/bin/sh -e

# Install and use 'eatmydata' in builds where available
if apt-get --yes --option=APT::Install-Recommends=false install eatmydata; then
   printf " /usr/lib/libeatmydata/libeatmydata.so" >> /etc/ld.so.preload
fi

# Have 'ccache' ready in builds
apt-get --yes --option=APT::Install-Recommends=false install ccache || true
""",
                                                     help_text="""\
Script that will be run via sbuild's '--chroot-setup-command'.
<br />
Example:
<pre>
#!/bin/sh -e

# Install and use 'eatmydata' in builds where available
if apt-get --yes --option=APT::Install-Recommends=false install eatmydata; then
   printf " /usr/lib/libeatmydata/libeatmydata.so" >> /etc/ld.so.preload
fi

# Have 'ccache' ready in builds
apt-get --yes --option=APT::Install-Recommends=false install ccache || true

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
                                                  default="""\
# Enable ccache
$path = '/usr/lib/ccache:/usr/sbin:/usr/bin:/sbin:/bin:/usr/X11R6/bin:/usr/games';
$build_environment = { 'CCACHE_DIR' => '%LIBDIR%/.ccache' };
""",
                                                  help_text="""\
Perl snippet to be added in the .sbuildrc for each build.; you may use these placeholders:<br />
<br />
%LIBDIR%: Per-chroot persistent dir; may be used for data that should persist beteeen builds (caches, ...).<br />
<br />
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
            ("Chroot setup options", {"classes": ("collapse",), "fields": ("chroot_setup_script", "sbuildrc_snippet")}),
            ("Extra Options", {"classes": ("collapse",),
                               "description": """
<b>Supported extra options</b>
<p><em>Internal-APT-Priority: N</em>: Set APT priority for internal apt sources in builds.</p>
<p>
The default is 1, which means you will only build against newer
packages in our own repositories in case it's really needed by
the build dependencies. This is the recommended behaviour,
producing sparse dependencies.
</p>
<p>
However, some packages with incorrect build dependencies might
break anyway, while they would work fine when just build against
the newest version available.
</p>
<p>
So, in case you don't care about sparse dependencies, you can
pimp the internal priority up here.
</p>
<p>
<em>Example</em>:
<tt>Internal-APT-Priority: 500</tt>: Always build against newer internal packages.
</p>
""",
                               "fields": ("extra_options",)}),)

        inlines = (ArchitectureOptionInline,)
        filter_horizontal = ("extra_sources", "components",)

        @classmethod
        def mbd_meta_add_base_sources(cls, msglog):
            "Add default distribution objects for all base sources found."
            def default_components(origin):
                return {"Ubuntu": ["main", "universe", "restricted", "multiverse"]}.get(origin, ["main", "contrib", "non-free"])

            for s in mini_buildd.models.source.Source.Admin.mbd_filter_active_base_sources():
                new_dist, created = Distribution.mbd_get_or_create(msglog, base_source=s)

                if created:
                    if not mini_buildd.misc.codename_has_lintian_suppress(s.codename):
                        new_dist.lintian_mode = Distribution.LINTIAN_RUN_ONLY

                    # Auto-add known default components or Origin
                    for c in default_components(s.origin):
                        component = mini_buildd.models.source.Component.objects.get(name__exact=c)
                        new_dist.components.add(component)

                    # Auto-add extra sources that start with our base_source's codename
                    for prio_source in mini_buildd.models.source.PrioritySource.objects.filter(source__codename__regex=r"^{c}-".format(c=s.codename)):
                        new_dist.extra_sources.add(prio_source)

                    # Auto-add all locally supported archs
                    archall = True
                    for arch in mini_buildd.models.source.Architecture.mbd_supported_architectures():
                        architecture = mini_buildd.models.source.Architecture.objects.get(name__exact=arch)
                        architecture_option = ArchitectureOption(architecture=architecture,
                                                                 distribution=new_dist,
                                                                 build_architecture_all=archall)
                        architecture_option.save()
                        archall = False

                    # Save changes to Distribution model
                    new_dist.save()

    def __unicode__(self):
        return "{o} '{b}': {c} ({a}) + ({x})".format(o=self.base_source.origin,
                                                     b=self.base_source.codename,
                                                     c=" ".join(self.mbd_get_components()),
                                                     a=" ".join(self.mbd_get_architectures(show_opt_flag=True)),
                                                     x=", ".join(["{c}:{p}".format(c=e.source.codename, p=e.priority) for e in self.extra_sources.all()]))

    def mbd_get_components(self):
        return [c.name for c in sorted(self.components.all(), cmp=mini_buildd.models.source.cmp_components)]

    def mbd_get_architectures(self, show_opt_flag=False):
        return ["{a}{o}".format(a=a.architecture.name, o="*" if (show_opt_flag and a.optional) else "") for a in self.architectureoption_set.all()]

    def mbd_get_archall_architectures(self):
        return [a.architecture.name for a in self.architectureoption_set.all() if a.build_architecture_all]

    def mbd_get_mandatory_architectures(self):
        return [a.architecture.name for a in self.architectureoption_set.all() if not a.optional]

    def mbd_get_apt_line(self, repository, suite_option, rollback=None, prefix="deb "):
        return "{p}{u}{r}/{i}/ {d} {c}".format(
            p=prefix,
            u=self.mbd_get_daemon().model.mbd_get_http_url(),
            r=os.path.basename(mini_buildd.setup.REPOSITORIES_DIR),
            i=repository.identity,
            d=suite_option.mbd_get_distribution_string(repository, self, rollback=rollback),
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
        internal_prio = self.mbd_get_extra_option("Internal-APT-Priority", 1)
        for s in repository.mbd_get_internal_suite_dependencies(suite_option):
            result += s.mbd_get_apt_preferences(repository, self, prio=internal_prio) + "\n"

        return result

    def mbd_get_sbuildrc_snippet(self, arch):
        libdir = os.path.join(mini_buildd.setup.CHROOTS_DIR, self.base_source.codename, arch, mini_buildd.setup.CHROOT_LIBDIR)
        # Note: For some reason (python, django sqlite, browser?) the text field may be in DOS mode.
        return mini_buildd.misc.fromdos(mini_buildd.misc.subst_placeholders(self.sbuildrc_snippet, {"LIBDIR": libdir}))

    def mbd_get_reverse_dependencies(self):
        "When the distribution changes, all repos that use that distribution also change."
        return [r for r in self.repository_set.all()]


class Repository(mini_buildd.models.base.StatusModel):
    identity = django.db.models.CharField(primary_key=True, max_length=50, default="test",
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
<br />
Example:
<pre>
# Allow Debian maintainers (must install the 'debian-keyring' package)
/usr/share/keyrings/debian-keyring.gpg
# Allow from some local keyring file
/etc/my-schlingels.gpg
</pre>
""")

    notify = django.db.models.ManyToManyField(EmailAddress,
                                              blank=True,
                                              help_text="Addresses that get all notification emails unconditionally.")
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
        filter_horizontal = ("distributions", "notify",)

        def get_readonly_fields(self, _request, obj=None):
            "Forbid change identity on existing repository."
            fields = copy.copy(self.readonly_fields)
            if obj:
                fields.append("identity")
            return fields

        @classmethod
        def mbd_meta_build_keyring_packages(cls, msglog):
            if not Repository.mbd_get_daemon().is_running():
                raise Exception("Daemon needs to be running to build keyring packages")
            for s in Repository.mbd_get_active():
                s.mbd_build_keyring_packages(msglog.request)

        @classmethod
        def mbd_meta_build_test_packages(cls, msglog):
            if not Repository.mbd_get_daemon().is_running():
                raise Exception("Daemon needs to be running to build test packages")
            for s in Repository.mbd_get_active():
                s.mbd_build_test_packages(msglog.request)

        @classmethod
        def mbd_meta_add_sandbox(cls, msglog):
            "Add sandbox repository 'test'."
            sandbox_repo, created = Repository.mbd_get_or_create(
                msglog,
                identity="test",
                allow_unauthenticated_uploads=True,
                layout=Layout.objects.get(name__exact="Default"))
            if created:
                for d in Distribution.objects.all():
                    sandbox_repo.distributions.add(d)

        @classmethod
        def mbd_meta_add_debdev(cls, msglog):
            "Add developer repository 'debdev', only for sid."
            try:
                sid = Distribution.objects.get(base_source__codename="sid")
            except:
                raise Exception("No 'sid' distribution found")
            debdev_repo, created = Repository.mbd_get_or_create(
                msglog,
                identity="debdev",
                layout=Layout.objects.get(name__exact="Debian Developer"),
                extra_uploader_keyrings="""\
# Allow Debian maintainers (must install the 'debian-keyring' package)
/usr/share/keyrings/debian-keyring.gpg
""")
            if created:
                debdev_repo.distributions.add(sid)

    def __unicode__(self):
        return "{i}: {d}".format(i=self.identity, d=" ".join([d.base_source.codename for d in self.distributions.all()]))

    def clean(self, *args, **kwargs):
        self.mbd_validate_regex(r"^[a-z0-9]+$", self.identity, "Identity")
        super(Repository, self).clean(*args, **kwargs)

    def _mbd_portext2keyring_suites(self, request, dsc_url):
        for d in self.distributions.all():
            for s in self.layout.suiteoption_set.all().filter(build_keyring_package=True):
                dist = s.mbd_get_distribution_string(self, d)
                info = "Port for {d}: {p}".format(d=dist, p=os.path.basename(dsc_url))
                try:
                    self.mbd_get_daemon().portext(dsc_url, dist)
                    MsgLog(LOG, request).info("Requested: {i}".format(i=info))
                except Exception as e:
                    mini_buildd.setup.log_exception(MsgLog(LOG, request), "FAILED: {i}".format(i=info), e)

    def mbd_build_keyring_packages(self, request):
        with contextlib.closing(self.mbd_get_daemon().get_keyring_package()) as package:
            self._mbd_portext2keyring_suites(request, "file://" + package.dsc)

    def mbd_build_test_packages(self, request):
        for t in ["archall", "cpp", "ftbfs"]:
            with contextlib.closing(self.mbd_get_daemon().get_test_package(t)) as package:
                self._mbd_portext2keyring_suites(request, "file://" + package.dsc)

    def mbd_get_uploader_keyring(self):
        gpg = mini_buildd.gnupg.TmpGnuPG()
        # Add keys from django users
        # pylint: disable=E1101
        for u in django.contrib.auth.models.User.objects.filter(is_active=True):
            # pylint: enable=E1101
            LOG.debug("Checking user: {u}".format(u=u))

            uploader = None
            try:
                uploader = u.get_profile()
            except:
                LOG.warn("User '{u}' does not have an uploader profile (deliberately removed?)".format(u=u))

            if uploader and uploader.mbd_is_active() and uploader.may_upload_to.all().filter(identity=self.identity):
                LOG.info("Adding uploader key for '{r}': {k}: {n}".format(r=self, k=uploader.key_long_id, n=uploader.key_name))
                gpg.add_pub_key(uploader.key)

        # Add configured extra keyrings
        for l in self.extra_uploader_keyrings.splitlines():
            l = l.strip()
            if l and l[0] != "#":
                LOG.info("Adding keyring: {k}".format(k=l))
                gpg.add_keyring(l)
        return gpg

    def mbd_get_path(self):
        return os.path.join(mini_buildd.setup.REPOSITORIES_DIR, self.identity)

    def mbd_get_description(self, distribution, suite_option):
        return "{s} packages for {d}-{i}".format(s=suite_option.suite.name, d=distribution.base_source.codename, i=self.identity)

    def mbd_get_meta_distributions(self, distribution, suite_option):
        try:
            result = []
            for p in self.layout.mbd_get_extra_option("Meta-Distributions", "").split():
                meta, d = p.split("=")
                dist = "{c}-{r}-{s}".format(c=d.split("-")[0], r=self.identity, s=d.split("-")[1])
                if dist == suite_option.mbd_get_distribution_string(self, distribution):
                    result.append(meta)
            return result
        except Exception as e:
            # Raise Exception with human-readable text
            raise Exception("Please fix syntax error in extra option 'Meta-Distributions' in layout '{l}': {e}".format(l=self.layout, e=e))

    def mbd_distribution_strings(self, **suiteoption_filter):
        "Return a list with all full distributions strings, optionally matching a suite options filter (unstable, experimental,...)."
        result = []
        for d in self.distributions.all():
            result += [s.mbd_get_distribution_string(self, d) for s in self.layout.suiteoption_set.filter(**suiteoption_filter)]
        return result

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
AlsoAcceptFor: {meta_distributions}
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
                    meta_distributions=" ".join(self.mbd_get_meta_distributions(d, s)),
                    origin=self.mbd_get_daemon().model.mbd_get_archive_origin(),
                    components=" ".join(d.mbd_get_components()),
                    architectures=" ".join([x.name for x in d.architectures.all()]),
                    desc=self.mbd_get_description(d, s),
                    na="yes" if s.not_automatic else "no",
                    bau="yes" if s.but_automatic_upgrades else "no")

                for r in range(s.rollback):
                    result += dist_template.format(
                        distribution=s.mbd_get_distribution_string(self, d, r),
                        meta_distributions="",
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
            dsc = "{r}/pool/{c}/{d}/{p}/{dsc}".format(r=self.identity, c=c.name, d=subdir, p=package,
                                                      dsc=mini_buildd.changes.Changes.gen_dsc_file_name(package, version))
            LOG.debug("Checking dsc: {d}".format(d=dsc))
            if os.path.exists(os.path.join(mini_buildd.setup.REPOSITORIES_DIR, dsc)):
                return c.name, os.path.join(self.mbd_get_daemon().model.mbd_get_http_url(), os.path.basename(mini_buildd.setup.REPOSITORIES_DIR), dsc)

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

    def mbd_package_notify(self, status, distribution, pkg, body, extra=None, message=None, msglog=LOG):
        pkg_log = mini_buildd.misc.PkgLog(self.identity, True, pkg["source"], pkg["sourceversion"])
        self.mbd_get_daemon().model.mbd_notify(mini_buildd.misc.pkg_fmt(status,
                                                                        distribution,
                                                                        pkg["source"],
                                                                        pkg["sourceversion"],
                                                                        extra=extra,
                                                                        message=message),
                                               body,
                                               repository=self,
                                               changes=mini_buildd.changes.Changes(pkg_log.changes) if pkg_log.changes else None,
                                               distribution=distribution,
                                               msglog=msglog)

    def _mbd_package_purge_orphaned_logs(self, package, msglog=LOG):
        pkg_show = self._mbd_reprepro().show(package)
        for pkg_log in glob.glob(mini_buildd.misc.PkgLog.get_path(self.identity, True, package, "*")):
            msglog.debug("Checking package log: {p}".format(p=pkg_log))
            if not self._mbd_package_find(pkg_show, version=os.path.basename(os.path.realpath(pkg_log))):
                shutil.rmtree(pkg_log, ignore_errors=True)
                msglog.info("Purging orphaned package log: {p}".format(p=pkg_log))

    def mbd_package_purge_orphaned_logs(self, package=None, msglog=LOG):
        if package:
            self._mbd_package_purge_orphaned_logs(package, msglog=msglog)
        else:
            for pkg_dir in glob.glob(mini_buildd.misc.PkgLog.get_path(self.identity, True, "[!_]*")):
                self._mbd_package_purge_orphaned_logs(os.path.basename(os.path.realpath(pkg_dir)), msglog=msglog)

    def _mbd_package_shift_rollbacks(self, distribution, suite_option, package_name):
        reprepro_output = ""
        for r in range(suite_option.rollback - 1, -1, -1):
            src = suite_option.mbd_get_distribution_string(self, distribution, None if r == 0 else r - 1)
            dst = suite_option.mbd_get_distribution_string(self, distribution, r)
            LOG.info("Rollback: Moving {p}: {s} to {d}".format(p=package_name, s=src, d=dst))
            try:
                reprepro_output += self._mbd_reprepro().migrate(package_name, src, dst)
            except Exception as e:
                mini_buildd.setup.log_exception(LOG, "Rollback failed (ignoring)", e)
        return reprepro_output

    def mbd_package_migrate(self, package, distribution, suite, rollback=None, version=None, msglog=LOG):
        reprepro_output = ""

        src_dist = suite.mbd_get_distribution_string(self, distribution)
        pkg_show = self._mbd_reprepro().show(package)
        src_pkg = None

        if rollback is not None:
            dst_dist = src_dist
            msglog.info("Rollback restore of '{p}' from rollback {r} to '{d}'".format(p=package, r=rollback, d=dst_dist))
            if self._mbd_package_find(pkg_show, distribution=dst_dist):
                raise Exception("Package '{p}' exists in '{d}': Remove first to restore rollback".format(p=package, d=dst_dist))

            rob_dist = suite.mbd_get_distribution_string(self, distribution, rollback=rollback)
            src_pkg = self._mbd_package_find(pkg_show, distribution=rob_dist, version=version)
            if src_pkg is None:
                raise Exception("Package '{p}' has no such version in rollback '{r}'".format(p=package, r=rollback))

            # Actually migrate package in reprepro
            reprepro_output += self._mbd_reprepro().migrate(package, rob_dist, dst_dist, version)
        else:
            # Get src and dst dist strings, and check we are configured to migrate
            if not suite.migrates_to:
                raise Exception("You can't migrate from '{d}'".format(d=src_dist))
            dst_dist = suite.migrates_to.mbd_get_distribution_string(self, distribution)

            # Check if package is in src_dst
            src_pkg = self._mbd_package_find(pkg_show, distribution=src_dist, version=version)
            if src_pkg is None:
                raise Exception("Package '{p}' not in '{d}'".format(p=package, d=src_dist))

            # Check that version is not already migrated
            dst_pkg = self._mbd_package_find(pkg_show, distribution=dst_dist)
            if dst_pkg is not None and src_pkg["sourceversion"] == dst_pkg["sourceversion"]:
                raise Exception("Version '{v}' already migrated to '{d}'".format(v=src_pkg["sourceversion"], d=dst_dist))

            # Shift rollbacks in the destination distributions
            if dst_pkg is not None:
                reprepro_output += self._mbd_package_shift_rollbacks(distribution, suite.migrates_to, package)

            # Actually migrate package in reprepro
            reprepro_output += self._mbd_reprepro().migrate(package, src_dist, dst_dist, version)

        # Finally, purge any now-maybe-orphaned package logs
        self.mbd_package_purge_orphaned_logs(package, msglog=msglog)

        # Notify
        self.mbd_package_notify("MIGRATED", dst_dist, src_pkg, reprepro_output, msglog=msglog)

        return reprepro_output

    def mbd_package_remove(self, package, distribution, suite, rollback=None, version=None, msglog=LOG):
        reprepro_output = ""

        dist_str = suite.mbd_get_distribution_string(self, distribution, rollback)
        src_pkg = self.mbd_package_find(package, distribution=dist_str, version=version)
        if not src_pkg:
            raise Exception("Package '{p}' not in '{d}'".format(p=package, d=dist_str))

        if rollback is None:
            # Shift rollbacks
            reprepro_output += self._mbd_package_shift_rollbacks(distribution, suite, package)
            # Remove package
            reprepro_output += self._mbd_reprepro().remove(package, dist_str, version)
        else:
            # Rollback removal
            reprepro_output += self._mbd_reprepro().remove(package, dist_str, version)

            # Fix up empty rollback dist
            for r in range(rollback, suite.rollback - 1):
                src = suite.mbd_get_distribution_string(self, distribution, r + 1)
                dst = suite.mbd_get_distribution_string(self, distribution, r)
                try:
                    reprepro_output += self._mbd_reprepro().migrate(package, src, dst)
                    reprepro_output += self._mbd_reprepro().remove(package, src)
                except Exception as e:
                    mini_buildd.setup.log_exception(msglog,
                                                    "Rollback: Moving '{p}' from '{s}' to '{d}' FAILED (ignoring)".format(p=package, s=src, d=dst),
                                                    e,
                                                    logging.WARN)

        # Finally, purge any now-maybe-orphaned package logs
        self.mbd_package_purge_orphaned_logs(package, msglog=msglog)

        # Notify
        self.mbd_package_notify("REMOVED", dist_str, src_pkg, reprepro_output, msglog=msglog)

        return reprepro_output

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

    def _mbd_package_install(self, bres, dist_str):
        with contextlib.closing(mini_buildd.misc.TmpDir()) as t:
            bres.untar(path=t.tmpdir)
            self._mbd_reprepro().install(" ".join(glob.glob(os.path.join(t.tmpdir, "*.changes"))),
                                         dist_str)
            LOG.info("Installed: {p} ({d})".format(p=bres.get_pkg_id(with_arch=True), d=dist_str))

    def mbd_package_install(self, distribution, suite_option, changes, bresults):
        """
        Install a dict arch:bres of successful build results.
        """
        # Get the full distribution str
        dist_str = suite_option.mbd_get_distribution_string(self, distribution)

        # Check that all mandatory archs are present
        missing_mandatory_archs = [arch for arch in distribution.mbd_get_mandatory_architectures() if arch not in bresults]
        if missing_mandatory_archs:
            raise Exception("{n} mandatory architecture(s) missing: {a}".format(n=len(missing_mandatory_archs), a=" ".join(missing_mandatory_archs)))

        # Get the (source) package name
        package = changes["Source"]
        LOG.debug("Package install: Package={p}".format(p=package))

        # Shift current package up in the rollback distributions (unless this is the initial install)
        if self.mbd_package_find(package, distribution=dist_str):
            self._mbd_package_shift_rollbacks(distribution, suite_option, package)

        # First, install the dsc
        self._mbd_reprepro().install_dsc(changes.dsc_file_name, dist_str)

        # Second, install all build results
        for bres in bresults.values():
            # Don't try install if skipped
            if bres.get("Sbuild-Status") == "skipped":
                LOG.info("Skipped: {p} ({d})".format(p=bres.get_pkg_id(with_arch=True), d=bres["Distribution"]))
            else:
                self._mbd_package_install(bres, dist_str)

        # Finally, purge any now-maybe-orphaned package logs
        self.mbd_package_purge_orphaned_logs(package)

    def mbd_prepare(self, _request):
        """
        Idempotent repository preparation. This may be used as-is as mbd_sync.
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

    def mbd_sync(self, request):
        self.mbd_prepare(request)

    def mbd_remove(self, _request):
        if os.path.exists(self.mbd_get_path()):
            shutil.rmtree(self.mbd_get_path())

    def mbd_check(self, request):
        # Reprepro check
        MsgLog(LOG, request).log_text(self._mbd_reprepro().check())

        # Purge orphaned logs.
        # Note: This may take some time on bigger repos. We
        # usually run this per package on install/remove/migrate
        # anyway, so maybe this could eventually be moved to a
        # better place.
        self.mbd_package_purge_orphaned_logs(msglog=MsgLog(LOG, request))

    def mbd_get_dependencies(self):
        result = []
        for d in self.distributions.all():
            result.append(d.base_source)
            result += [e.source for e in d.extra_sources.all()]
        return result


def get_meta_distribution_map():
    " Get a dict of the meta distributions: meta -> actual. "
    result = {}
    for r in Repository.objects.all():
        for d in r.distributions.all():
            for s in r.layout.suiteoption_set.all():
                for m in r.mbd_get_meta_distributions(d, s):
                    result[m] = s.mbd_get_distribution_string(r, d)
    LOG.debug("Got meta distribution map: {m}".format(m=result))
    return result
