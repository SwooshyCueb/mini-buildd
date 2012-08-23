# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import codecs
import tempfile
import time
import shutil
import glob
import re
import socket
import logging

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

    def __unicode__(self):
        return "{n} <{a}>".format(n=self.name, a=self.address)


class Suite(mini_buildd.models.base.Model):
    name = django.db.models.CharField(
        max_length=100,
        help_text="A suite to support, usually s.th. like 'experimental', 'unstable', 'testing' or 'stable'.")

    def __unicode__(self):
        return self.name


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

    def mbd_get_distribution_string(self, repository, distribution):
        return "{c}-{i}-{s}".format(
            c=distribution.base_source.codename,
            i=repository.identity,
            s=self.suite.name)

    def mbd_get_apt_pin(self, repository, distribution):
        return "release n={c}, o={o}".format(
            c=self.mbd_get_distribution_string(repository, distribution),
            o=self.mbd_get_daemon().model.mbd_get_archive_origin())

    def mbd_get_apt_preferences(self, repository, distribution, prio=500):
        return "Package: *\nPin: {pin}\nPin-Priority: {prio}\n".format(
            pin=self.mbd_get_apt_pin(repository, distribution),
            prio=prio)


class SuiteOptionInline(django.contrib.admin.TabularInline):
    model = SuiteOption
    extra = 1


class Layout(mini_buildd.models.base.Model):
    name = django.db.models.CharField(primary_key=True, max_length=100)

    suites = django.db.models.ManyToManyField(Suite, through=SuiteOption)

    # Version magic
    default_version = django.db.models.CharField(
        max_length=100, default="~%IDENTITY%%CODEVERSION%+1",
        help_text="""This will be used for automated builds; you may use these placeholders:<br/>

%IDENTITY%: Repository identity (see 'Repository').<br/>
%CODEVERSION%: Numerical base distribution version (see 'Source').
""")
    mandatory_version_regex = django.db.models.CharField(
        max_length=100, default="~%IDENTITY%%CODEVERSION%\+[1-9]",
        help_text="Mandatory version regex; you may use the same placeholders as for 'default version'.")

    # Version magic (experimental)
    experimental_default_version = django.db.models.CharField(
        max_length=30, default="~%IDENTITY%%CODEVERSION%+0",
        help_text="Like 'default version', but for suites flagged 'experimental'.")

    experimental_mandatory_version_regex = django.db.models.CharField(
        max_length=100, default="~%IDENTITY%%CODEVERSION%\+0",
        help_text="Like 'mandatory version', but for suites flagged 'experimental'.")

    class Admin(mini_buildd.models.base.Model.Admin):
        fieldsets = (
            ("Basics", {"fields": ("name",)}),
            ("Version Options", {"classes": ("collapse",),
                                 "fields": ("default_version", "mandatory_version_regex",
                                            "experimental_default_version", "experimental_mandatory_version_regex")}),)
        inlines = (SuiteOptionInline,)

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


class ArchitectureOption(mini_buildd.models.base.Model):
    architecture = django.db.models.ForeignKey("Architecture")
    distribution = django.db.models.ForeignKey("Distribution")

    optional = django.db.models.BooleanField(default=False)
    build_architecture_all = django.db.models.BooleanField(default=False)

    class Meta(mini_buildd.models.base.Model.Meta):
        unique_together = ("architecture", "distribution")

    def clean(self, *args, **kwargs):
        if self.build_architecture_all and self.optional:
            raise django.core.exceptions.ValidationError("Optional architectures must not be architecture all!")
        super(ArchitectureOption, self).clean(*args, **kwargs)


class ArchitectureOptionInline(django.contrib.admin.TabularInline):
    model = ArchitectureOption
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
    build_dep_resolver = django.db.models.IntegerField(choices=RESOLVER_CHOICES, default=RESOLVER_APT)

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

# Have ccache ready in builds
apt-get --yes --no-install-recommends install ccache

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

    def __unicode__(self):
        def xtra():
            result = ""
            for e in self.extra_sources.all():
                result += "+ " + e.mbd_id()
            return result

        return "{b} {e} [{c}]".format(b=self.base_source.mbd_id(), e=xtra(), c=" ".join(self.mbd_get_components()))

    def mbd_get_components(self):
        return [c.name for c in self.components.all()]

    def mbd_get_apt_line(self, repository, suite_option):
        return "deb {u}/{r}/{i} {d} {c}".format(
            u=self.mbd_get_daemon().model.mbd_get_http_url(),
            r=os.path.basename(mini_buildd.setup.REPOSITORIES_DIR),
            i=repository.identity, d=suite_option.mbd_get_distribution_string(repository, self), c=" ".join(self.mbd_get_components()))

    def mbd_get_apt_sources_list(self, repository, suite_option):
        result = "# Base: {p}\n".format(p=self.base_source.mbd_get_apt_pin())
        result += self.base_source.mbd_get_apt_line() + "\n\n"
        for e in self.extra_sources.all():
            result += "# Extra: {p}\n".format(p=e.source.mbd_get_apt_pin())
            result += e.source.mbd_get_apt_line() + "\n"
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


class Repository(mini_buildd.models.base.StatusModel):
    identity = django.db.models.CharField(primary_key=True, max_length=50, default=socket.gethostname())

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

# pylint: disable=R0201
        def action_generate_keyring_packages(self, request, queryset):
            for s in queryset:
                if s.mbd_is_active():
                    s.mbd_generate_keyring_packages(request)
                else:
                    s.mbd_msg_warn(request, "Repository not activated: {r}".format(r=s))
        action_generate_keyring_packages.short_description = "[X] Generate keyring packages"
# pylint: enable=R0201

        actions = mini_buildd.models.base.StatusModel.Admin.actions + [action_generate_keyring_packages]

    def __unicode__(self):
        return "{i}: {d} dists ({s})".format(i=self.identity, d=len(self.distributions.all()), s=self.mbd_get_status_display())

    def mbd_check_version(self, version, distribution, suite_option):
        mandatory_regex = self.layout.mbd_get_mandatory_version_regex(self, distribution, suite_option)
        if not re.compile(mandatory_regex).search(version):
            raise Exception("Mandatory version check failed for suite '{s}': '{m}' not in '{v}'".format(s=suite_option.suite.name, m=mandatory_regex, v=version))

    def mbd_generate_keyring_packages(self, request):
        t = tempfile.mkdtemp()
        try:
            p = os.path.join(t, "package")
            shutil.copytree("/usr/share/doc/mini-buildd/examples/packages/archive-keyring-template", p)

            identity = self.mbd_get_daemon().model.identity
            debemail = self.mbd_get_daemon().model.email_address
            debfullname = self.mbd_get_daemon().model.mbd_fullname
            hopo = self.mbd_get_daemon().model.mbd_get_ftp_hopo()

            for root, _dirs, files in os.walk(p):
                for f in files:
                    old_file = os.path.join(root, f)
                    new_file = old_file + ".new"
                    codecs.open(new_file, "w", encoding="UTF-8").write(
                        mini_buildd.misc.subst_placeholders(
                            codecs.open(old_file, "r", encoding="UTF-8").read(),
                            {"ID": identity,
                             "MAINT": "{n} <{e}>".format(n=debfullname, e=debemail)}))
                    os.rename(new_file, old_file)

            package_name = "{i}-archive-keyring".format(i=identity)
            self.mbd_get_daemon().model.mbd_gnupg.export(os.path.join(p, package_name + ".gpg"))

            env = mini_buildd.misc.taint_env({"DEBEMAIL": debemail, "DEBFULLNAME": debfullname})

            version = time.strftime("%Y%m%d%H%M%S", time.gmtime())
            for d in self.distributions.all():
                for s in self.layout.suiteoption_set.all().filter(build_keyring_package=True):
                    mini_buildd.misc.call(["debchange",
                                           "--create",
                                           "--package={p}".format(p=package_name),
                                           "--newversion={v}{m}".format(v=version, m=self.layout.mbd_get_default_version(self, d, s)),
                                           "--force-distribution",
                                           "--force-bad-version",
                                           "--dist={c}-{i}-{s}".format(c=d.base_source.codename, i=self.identity, s=s.suite.name),
                                           "Automated build for via mini-buildd."],
                                          cwd=p,
                                          env=env)
                    mini_buildd.misc.call(["dpkg-buildpackage", "-S", "-sa"],
                                          cwd=p,
                                          env=env)
                    # Remove changelog for next package build
                    os.remove(os.path.join(p, "debian", "changelog"))

            for c in glob.glob(os.path.join(t, "*.changes")):
                mini_buildd.changes.Changes(c).upload(hopo)
                self.mbd_msg_info(request, "Keyring package uploaded: {c}".format(c=c))

        except Exception as e:
            self.mbd_msg_exception(request, "Some package failed", e)

        finally:
            shutil.rmtree(t)

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

    def _mbd_find_dist(self, dist):
        base, identity, suite = mini_buildd.misc.parse_distribution(dist)
        LOG.debug("Finding dist for {d}: Base={b}, RepoId={r}, Suite={s}".format(d=dist, b=base, r=identity, s=suite))

        if identity == self.identity:
            for d in self.distributions.all():
                if d.base_source.codename == base:
                    for s in self.layout.suiteoption_set.all():
                        if s.suite.name == suite:
                            return d, s
        raise Exception("No such distribution in repository {i}: {d}".format(self.identity, d=dist))

    def mbd_get_apt_keys(self, dist):
        d, _s = self._mbd_find_dist(dist)
        result = self.mbd_get_daemon().model.mbd_get_pub_key()
        for e in d.extra_sources.all():
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

    def mbd_get_chroot_setup_script(self, dist):
        d, _s = self._mbd_find_dist(dist)
        # Note: For some reason (python, django sqlite, browser?) the text field may be in DOS mode.
        return mini_buildd.misc.fromdos(d.chroot_setup_script)

    def mbd_get_sbuildrc_snippet(self, dist, arch):
        d, _s = self._mbd_find_dist(dist)
        libdir = os.path.join(mini_buildd.setup.CHROOTS_DIR, d.base_source.codename, arch, mini_buildd.setup.CHROOT_LIBDIR)

        # Note: For some reason (python, django sqlite, browser?) the text field may be in DOS mode.
        return mini_buildd.misc.fromdos(mini_buildd.misc.subst_placeholders(d.sbuildrc_snippet, {"LIBDIR": libdir}))

    def _mbd_reprepro_config(self):
        result = ""
        for d in self.distributions.all():
            for s in self.layout.suiteoption_set.all():
                result += """
Codename: {dist}
Suite: {dist}
Label: {dist}
Origin: {origin}
Components: {components}
Architectures: source {architectures}
Description: {desc}
SignWith: default
NotAutomatic: {na}
ButAutomaticUpgrades: {bau}
DebIndices: Packages Release . .gz .bz2
DscIndices: Sources Release . .gz .bz2
""".format(dist=s.mbd_get_distribution_string(self, d),
           origin=self.mbd_get_daemon().model.mbd_get_archive_origin(),
           components=" ".join(d.mbd_get_components()),
           architectures=" ".join([x.name for x in d.architectures.all()]),
           desc=self.mbd_get_description(d, s),
           na="yes" if s.not_automatic else "no",
           bau="yes" if s.but_automatic_upgrades else "no")

        return result

    def _mbd_reprepro(self):
        return mini_buildd.reprepro.Reprepro(basedir=self.mbd_get_path())

    def mbd_package_install(self, bres):
        t = tempfile.mkdtemp()
        bres.untar(path=t)
        self._mbd_reprepro().include(
            bres["Distribution"],
            " ".join(glob.glob(os.path.join(t, "*.changes"))))
        shutil.rmtree(t)
        LOG.info("Installed: {p} ({d})".format(p=bres.get_pkg_id(with_arch=True), d=bres["Distribution"]))

    def mbd_package_propagate(self, dest_distribution, source_distribution, package, version):
        return self._mbd_reprepro().copysrc(dest_distribution, source_distribution, package, version)

    def mbd_package_remove(self, distribution, package, version):
        return self._mbd_reprepro().removesrc(distribution, package, version)

    MBD_SEARCH_FMT_STANDARD = 0
    MBD_SEARCH_FMT_VERSIONS = 1

    def mbd_package_search(self, codename, pattern, fmt=MBD_SEARCH_FMT_STANDARD):
        """
        Result if of the form:

        { PACKAGE: { DISTRIBUTION: { VERSION: { PROPKEY: PROPVAL }}}}
        """
        distributions = []
        for d in self.distributions.all():
            if not codename or codename == d.base_source.codename:
                distributions.append(d)

        result = [{}, []]
        for d in distributions:
            for s in self.layout.suiteoption_set.all():
                for item in self._mbd_reprepro().listmatched(s.mbd_get_distribution_string(self, d), pattern):
                    package, distribution, version = item
                    pkg = result[self.MBD_SEARCH_FMT_STANDARD].setdefault(package, {})
                    dis = pkg.setdefault(distribution, {})
                    ver = dis.setdefault(version, {})
                    result[self.MBD_SEARCH_FMT_VERSIONS].append(version)
                    if s.migrates_to:
                        ver["migrates_to"] = s.migrates_to.mbd_get_distribution_string(self, d)

        return result[fmt]

    def mbd_prepare(self, request):
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

        # Reprepro config
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

        # Update all indices (or create on initial install) via reprepro
        repo = self._mbd_reprepro()
        repo.clearvanished()
        repo.export()

        self.mbd_msg_info(request, "{r}: Reprepro repository checked and updated: {b}".format(r=self, b=self.mbd_get_path()))

    def mbd_unprepare(self, request):
        if os.path.exists(self.mbd_get_path()):
            shutil.rmtree(self.mbd_get_path())
            self.mbd_msg_info(request, "{r}: Reprepro repository has been purged (along with all packages): {b}".format(r=self, b=self.mbd_get_path()))

    def mbd_check(self, request):
        self.mbd_prepare(request)

    def mbd_get_status_dependencies(self):
        result = []
        for d in self.distributions.all():
            result.append(d.base_source)
            for e in d.extra_sources.all():
                result.append(e.source)
        return result
