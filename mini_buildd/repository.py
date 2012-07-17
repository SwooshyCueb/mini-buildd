# -*- coding: utf-8 -*-
import StringIO
import os
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

from mini_buildd.models import Model, StatusModel, Architecture, Source, PrioritySource, Component, msg_info, msg_warn, msg_error

log = logging.getLogger(__name__)


class EmailAddress(Model):
    address = django.db.models.EmailField(primary_key=True, max_length=255)
    name = django.db.models.CharField(blank=True, max_length=255)

    class Meta:
        verbose_name_plural = "Email addresses"

    def __unicode__(self):
        return u"{n} <{a}>".format(n=self.name, a=self.address)

django.contrib.admin.site.register(EmailAddress)


class Suite(Model):
    name = django.db.models.CharField(
        max_length=100,
        help_text="A suite to support, usually s.th. like 'experimental', 'unstable','testing' or 'stable'.")
    experimental = django.db.models.BooleanField(default=False)

    migrates_from = django.db.models.ForeignKey(
        'self', blank=True, null=True,
        help_text="Leave this blank to make this suite uploadable, or chose a suite where this migrates from.")
    not_automatic = django.db.models.BooleanField(default=True)
    but_automatic_upgrades = django.db.models.BooleanField(default=False)

    def __unicode__(self):
        return u"{e}{n}{e} <= {m}".format(n=self.name,
                                          e=u"*" if self.experimental else u"",
                                          m=self.migrates_from.name if self.migrates_from else "User uploads")

django.contrib.admin.site.register(Suite)


class Layout(Model):
    name = django.db.models.CharField(primary_key=True, max_length=100)
    suites = django.db.models.ManyToManyField(Suite)
    build_keyring_package_for = django.db.models.ManyToManyField(Suite, blank=True, related_name="KeyringSuites")

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

    def __unicode__(self):
        return self.name

    @classmethod
    def _mbd_subst_placeholders(cls, value, repository, dist):
        return mini_buildd.misc.subst_placeholders(
            value,
            {"IDENTITY": repository.identity,
             "CODEVERSION": dist.base_source.codeversion})

    def mbd_get_mandatory_version_regex(self, repository, dist, suite):
        return self._mbd_subst_placeholders(
            self.experimental_mandatory_version_regex if suite.experimental else self.mandatory_version_regex,
            repository, dist)

    def mbd_get_default_version(self, repository, dist, suite):
        return self._mbd_subst_placeholders(
            self.experimental_default_version if suite.experimental else self.default_version,
            repository, dist)

    class Admin(django.contrib.admin.ModelAdmin):
        fieldsets = (
            ("Basics", {"fields": ("name", "suites", "build_keyring_package_for")}),
            ("Extra", {"classes": ("collapse",), "fields":
                           ("default_version", "mandatory_version_regex",
                            "experimental_default_version", "experimental_mandatory_version_regex")}),)

django.contrib.admin.site.register(Layout, Layout.Admin)


class Distribution(Model):
    base_source = django.db.models.ForeignKey(Source)
    extra_sources = django.db.models.ManyToManyField(PrioritySource, blank=True)
    components = django.db.models.ManyToManyField(Component)

    mandatory_architectures = django.db.models.ManyToManyField(Architecture)
    optional_architectures = django.db.models.ManyToManyField(Architecture, related_name="OptionalArchitecture", blank=True)
    architecture_all = django.db.models.ForeignKey(Architecture, related_name="ArchitectureAll")

    RESOLVER_APT = 0
    RESOLVER_APTITUDE = 1
    RESOLVER_INTERNAL = 2
    RESOLVER_CHOICES = (
        (RESOLVER_APT, "apt"),
        (RESOLVER_APTITUDE, "aptitude"),
        (RESOLVER_INTERNAL, "internal"))
    build_dep_resolver = django.db.models.SmallIntegerField(choices=RESOLVER_CHOICES, default=RESOLVER_APT)

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
    lintian_mode = django.db.models.SmallIntegerField(choices=LINTIAN_CHOICES, default=LINTIAN_FAIL_ON_ERROR)
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
    piuparts_mode = django.db.models.SmallIntegerField(choices=PIUPARTS_CHOICES, default=PIUPARTS_DISABLED)
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

    class Admin(django.contrib.admin.ModelAdmin):
        fieldsets = (
            ("Basics", {"fields": ("base_source", "extra_sources", "components")}),
            ("Architectures", {"fields": ("mandatory_architectures", "optional_architectures", "architecture_all")}),
            ("Build options", {"fields": ("build_dep_resolver", "apt_allow_unauthenticated", "lintian_mode", "lintian_extra_options")}),
            ("Extra", {"classes": ("collapse",), "fields": ("chroot_setup_script", "sbuildrc_snippet")}),)

    def __unicode__(self):
        def xtra():
            result = u""
            for e in self.extra_sources.all():
                result += "+ " + e.mbd_id()
            return result

        def cmps():
            result = u""
            for c in self.components.all():
                result += c.name + " "
            return result

        return u"{b} {e} [{c}]".format(b=self.base_source.mbd_id(), e=xtra(), c=cmps())

    def _mbd_clean_architectures(self):
        ".. todo:: Not enabled in clean() as code does not work there: ManyToMany fields keep old values until actually saved (??)."
        if not self.architecture_all in self.mandatory_architectures.all():
            raise django.core.exceptions.ValidationError("Architecture-All must be a mandatory architecture!")
        for ma in self.mandatory_architectures.all():
            for oa in self.optional_architectures.all():
                if ma.name == oa.name:
                    raise django.core.exceptions.ValidationError(u"Architecture {a} is in both, mandatory and optional architectures!".format(a=ma.name))

    def clean(self):
        # self._mbd_clean_architectures()
        super(Distribution, self).clean()

    def _mbd_get_architectures(self, m2m_objects):
        architectures = []
        for o in m2m_objects:
            for a in o.all():
                architectures.append(a.name)
        return architectures

    def mbd_get_mandatory_architectures(self):
        return self._mbd_get_architectures([self.mandatory_architectures])

    def mbd_get_optional_architectures(self):
        return self._mbd_get_architectures([self.optional_architectures])

    def mbd_get_all_architectures(self):
        return self._mbd_get_architectures([self.mandatory_architectures, self.optional_architectures])

    def mbd_get_apt_sources_list(self):
        res = "# Base: {p}\n".format(p=self.base_source.mbd_get_apt_pin())
        res += self.base_source.mbd_get_apt_line() + "\n\n"
        for e in self.extra_sources.all():
            res += "# Extra: {p}\n".format(p=e.source.mbd_get_apt_pin())
            res += e.source.mbd_get_apt_line() + "\n"
        return res


django.contrib.admin.site.register(Distribution, Distribution.Admin)


class Repository(StatusModel):
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

    external_home_url = django.db.models.URLField(blank=True)

    class Meta(StatusModel.Meta):
        verbose_name_plural = "Repositories"

    class Admin(StatusModel.Admin):
        fieldsets = (
            ("Basics", {"fields": ("identity", "layout", "distributions", "allow_unauthenticated_uploads", "extra_uploader_keyrings")}),
            ("Notify and extra options", {"fields": ("notify", "notify_changed_by", "notify_maintainer", "external_home_url")}),)

        def action_generate_keyring_packages(self, request, queryset):
            for s in queryset:
                if s.status >= s.STATUS_ACTIVE:
                    s.mbd_generate_keyring_packages(request)
                else:
                    msg_warn(request, "Repository not activated: {r}".format(r=s))
        action_generate_keyring_packages.short_description = "mini-buildd: 99 Generate keyring packages"

        actions = StatusModel.Admin.actions + [action_generate_keyring_packages]

    def __init__(self, *args, **kwargs):
        super(Repository, self).__init__(*args, **kwargs)
        log.debug("Initializing repository '{identity}'".format(identity=self.identity))

        self.mbd_uploadable_distributions = []
        for d in self.distributions.all():
            for s in self.layout.suites.all():
                if s.migrates_from is None:
                    self.mbd_uploadable_distributions.append(
                        "{d}-{identity}-{s}".format(identity=self.identity,
                                                    d=d.base_source.codename,
                                                    s=s.name))

    def __unicode__(self):
        return self.identity

    def mbd_check_version(self, version, dist, suite):
        mandatory_regex = self.layout.mbd_get_mandatory_version_regex(self, dist, suite)
        if not re.compile(mandatory_regex).search(version):
            raise Exception("Mandatory version check failed for suite '{s}': '{m}' not in '{v}'".format(s=suite.name, m=mandatory_regex, v=version))

    def mbd_generate_keyring_packages(self, request):
        t = tempfile.mkdtemp()
        try:
            p = os.path.join(t, "package")
            shutil.copytree("/usr/share/doc/mini-buildd/examples/packages/archive-keyring-template", p)

            identity = mini_buildd.daemon.get().model.identity
            debemail = mini_buildd.daemon.get().model.email_address
            debfullname = mini_buildd.daemon.get().model._fullname
            hopo = mini_buildd.daemon.get().model.mbd_get_ftp_hopo()

            for root, dirs, files in os.walk(p):
                for f in files:
                    old_file = os.path.join(root, f)
                    new_file = old_file + ".new"
                    open(new_file, "w").write(
                        mini_buildd.misc.subst_placeholders(
                            open(old_file, "r").read(),
                            {"ID": identity,
                             "MAINT": "{n} <{e}>".format(n=debfullname, e=debemail)}))
                    os.rename(new_file, old_file)

            package_name = "{i}-archive-keyring".format(i=identity)
            mini_buildd.daemon.get().model._gnupg.export(os.path.join(p, "keyrings", package_name + ".gpg"))

            env = mini_buildd.misc.taint_env({"DEBEMAIL": debemail, "DEBFULLNAME": debfullname})

            version = time.strftime("%Y%m%d%H%M%S", time.gmtime())
            mini_buildd.misc.call(["debchange",
                                   "--create",
                                   "--package={p}".format(p=package_name),
                                   "--newversion={v}".format(v=version),
                                   "Archive key automated build"],
                                  cwd=p,
                                  env=env)

            for d in self.distributions.all():
                for s in self.layout.build_keyring_package_for.all():
                    mini_buildd.misc.call(["debchange",
                                           "--newversion={v}{m}".format(v=version, m=self.layout.mbd_get_default_version(self, d, s)),
                                           "--force-distribution",
                                           "--force-bad-version",
                                           "--dist={c}-{i}-{s}".format(c=d.base_source.codename, i=self.identity, s=s.name),
                                           "Automated build for via mini-buildd."],
                                          cwd=p,
                                          env=env)
                    mini_buildd.misc.call(["dpkg-buildpackage", "-S", "-sa"],
                                          cwd=p,
                                          env=env)

            for c in glob.glob(os.path.join(t, "*.changes")):
                mini_buildd.changes.Changes(c).upload(hopo)
                msg_info(request, "Keyring package uploaded: {c}".format(c=c))

        except Exception as e:
            msg_error(request, "Some package failed: {e}".format(e=str(e)))
            pass
        finally:
            shutil.rmtree(t)

    def mbd_get_uploader_keyring(self):
        gpg = mini_buildd.gnupg.TmpGnuPG()
        # Add keys from django users
        for u in django.contrib.auth.models.User.objects.all():
            p = u.get_profile()
            for r in p.may_upload_to.all():
                if r.identity == self.identity:
                    gpg.add_pub_key(p.key)
                    log.info(u"Uploader key added for '{r}': {k}: {n}".format(r=self, k=p.key_long_id, n=p.key_name).encode("UTF-8"))
        # Add configured extra keyrings
        for l in self.extra_uploader_keyrings.splitlines():
            l = l.strip()
            if l and l[0] != "#":
                gpg.add_keyring(l)
                log.info("Adding keyring: {k}".format(k=l))
        return gpg

    def mbd_get_path(self):
        return os.path.join(mini_buildd.setup.REPOSITORIES_DIR, self.identity)

    def mbd_get_incoming_path(self):
        return os.path.join(self.mbd_get_path(), "incoming")

    def mbd_get_dist(self, dist, suite):
        return dist.base_source.codename + "-" + self.identity + "-" + suite.name

    def mbd_get_origin(self):
        return "mini-buildd" + self.identity

    def mbd_get_components(self):
        return "main contrib non-free"

    def mbd_get_desc(self, dist, suite):
        return "{d} {s} packages for {identity}".format(identity=self.identity, d=dist.base_source.codename, s=suite.name)

    def mbd_get_apt_line(self, dist, suite):
        import mini_buildd.daemon
        return "deb {u}/{r}/{i}/ {d} {c}".format(
            u=mini_buildd.daemon.get().model.mbd_get_http_url(),
            r=os.path.basename(mini_buildd.setup.REPOSITORIES_DIR),
            i=self.identity, d=self.mbd_get_dist(dist, suite), c=self.mbd_get_components())

    def mbd_find_dist(self, dist):
        base, identity, suite = mini_buildd.misc.parse_distribution(dist)
        log.debug("Finding dist for {d}: Base={b}, RepoId={r}, Suite={s}".format(d=dist, b=base, r=identity, s=suite))

        if identity == self.identity:
            for d in self.distributions.all():
                if d.base_source.codename == base:
                    for s in self.layout.suites.all():
                        if s.name == suite:
                            return d, s
        raise Exception("No such distribution in repository {i}: {d}".format(self.identity, d=dist))

    def mbd_get_apt_sources_list(self, dist):
        """
        .. todo::

        - get_apt_sources_list(): decide what other mini-buildd suites are to be included automatically
        """
        d, s = self.mbd_find_dist(dist)
        res = d.mbd_get_apt_sources_list()
        res += "\n"
        res += "# Mini-Buildd: {d}\n".format(d=dist)
        res += self.mbd_get_apt_line(d, s)
        return res

    def mbd_get_apt_preferences(self):
        ".. todo:: STUB"
        return ""

    def mbd_get_apt_keys(self, dist):
        d, s = self.mbd_find_dist(dist)
        import mini_buildd.daemon
        result = mini_buildd.daemon.get().model.mbd_get_pub_key()
        for e in d.extra_sources.all():
            for k in e.source.apt_keys.all():
                result += k.key
        return result

    def mbd_get_chroot_setup_script(self, dist):
        d, s = self.mbd_find_dist(dist)
        # Note: For some reason (python, django sqlite, browser?) the text field may be in DOS mode.
        return mini_buildd.misc.fromdos(d.chroot_setup_script)

    def mbd_get_sbuildrc_snippet(self, dist, arch):
        d, s = self.mbd_find_dist(dist)
        libdir = os.path.join(mini_buildd.setup.CHROOTS_DIR, d.base_source.codename, arch, mini_buildd.setup.CHROOT_LIBDIR)

        # Note: For some reason (python, django sqlite, browser?) the text field may be in DOS mode.
        return mini_buildd.misc.fromdos(mini_buildd.misc.subst_placeholders(d.sbuildrc_snippet, {"LIBDIR": libdir}))

    def mbd_get_sources(self, dist, suite):
        result = ""
        result += "Base: " + str(dist.base_source) + "\n"
        for e in dist.extra_sources.all():
            result += "Extra: " + str(e) + "\n"
        return result

    def mbd_reprepro_config(self):
        result = StringIO.StringIO()
        for d in self.distributions.all():
            for s in self.layout.suites.all():
                result.write("""
Codename: {dist}
Suite:  {dist}
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
""".format(dist=self.mbd_get_dist(d, s),
           origin=self.mbd_get_origin(),
           components=self.mbd_get_components(),
           architectures=" ".join(d.mbd_get_all_architectures()),
           desc=self.mbd_get_desc(d, s),
           na="yes" if s.not_automatic else "no",
           bau="yes" if s.but_automatic_upgrades else "no"))

        return result.getvalue()

    def mbd_reprepro(self):
        return mini_buildd.reprepro.Reprepro(self.mbd_get_path())

    def mbd_prepare(self, request):
        # Reprepro config
        mini_buildd.misc.mkdirs(os.path.join(self.mbd_get_path(), "conf"))
        mini_buildd.misc.mkdirs(self.mbd_get_incoming_path())
        open(os.path.join(self.mbd_get_path(), "conf", "distributions"), 'w').write(self.mbd_reprepro_config())
        open(os.path.join(self.mbd_get_path(), "conf", "incoming"), 'w').write("""\
Name: INCOMING
TempDir: /tmp
IncomingDir: {i}
Allow: {allow}
""".format(i=self.mbd_get_incoming_path(), allow=" ".join(self.mbd_uploadable_distributions)))

        open(os.path.join(self.mbd_get_path(), "conf", "options"), 'w').write("""\
gnupghome {h}
""".format(h=os.path.join(mini_buildd.setup.HOME_DIR, ".gnupg")))

        # Update all indices (or create on initial install) via reprepro
        repo = self.mbd_reprepro()
        repo.clearvanished()
        repo.export()

        msg_info(request, "Prepared repository '{i}' in '{b}'".format(i=self.identity, b=self.mbd_get_path()))

    def mbd_unprepare(self, request):
        if os.path.exists(self.mbd_get_path()):
            shutil.rmtree(self.mbd_get_path())
            msg_info(request, "Your repository has been purged, along with all packages: {d}".format(d=self.mbd_get_path()))

django.contrib.admin.site.register(Repository, Repository.Admin)
