# -*- coding: utf-8 -*-
import StringIO, os, re, datetime, socket, logging

import django.db, django.core.exceptions

from mini_buildd import setup, misc, reprepro

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
        primary_key=True, max_length=50,
        help_text="A suite to support, usually s.th. like 'unstable','testing' or 'stable'.")
    mandatory_version = django.db.models.CharField(
        max_length=50, default="~%IDENTITY%%CODEVERSION%\+[1-9]",
        help_text="""Mandatory version regex; you may use these placeholders:<br/>

%IDENTITY%: Repository identity<br/>
%CODEVERSION%: Numerical base distribution version (see Source Model).""")

    migrates_from = django.db.models.ForeignKey(
        'self', blank=True, null=True,
        help_text="Leave this blank to make this suite uploadable, or chose a suite where this migrates from.")
    not_automatic = django.db.models.BooleanField(default=True)
    but_automatic_upgrades = django.db.models.BooleanField(default=False)

    def __unicode__(self):
        return u"{n} ({m})".format(n=self.name, m=u"<= " + self.migrates_from.name if self.migrates_from else "uploadable")

    def mbd_get_mandatory_version(self, repository, dist):
        return misc.subst_placeholders(self.mandatory_version,
                                       { "IDENTITY": repository.identity,
                                         "CODEVERSION": dist.base_source.codeversion })

    def mbd_check_version(self, repository, dist, version):
        m = self.mbd_get_mandatory_version(repository, dist)
        regex = re.compile(m)
        if not regex.search(version):
            raise Exception("Mandatory version check failed for suite '{s}': '{m}' not in '{v}'".format(s=self.name, m=m, v=version))

django.contrib.admin.site.register(Suite)


class Layout(Model):
    name = django.db.models.CharField(primary_key=True, max_length=128,
                            help_text="Name for the layout.")
    suites = django.db.models.ManyToManyField(Suite)

    def __unicode__(self):
        return self.name

django.contrib.admin.site.register(Layout)


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
        (LINTIAN_DISABLED,        "Don't run lintian"),
        (LINTIAN_RUN_ONLY,        "Run lintian"),
        (LINTIAN_FAIL_ON_ERROR,   "Run lintian and fail on errors"),
        (LINTIAN_FAIL_ON_WARNING, "Run lintian and fail on warnings"))
    lintian_mode = django.db.models.SmallIntegerField(choices=LINTIAN_CHOICES, default=LINTIAN_FAIL_ON_ERROR)
    lintian_extra_options = django.db.models.CharField(max_length=200, default="--info")

    # piuparts not used atm; placeholder for later
    PIUPARTS_DISABLED = 0
    PIUPARTS_RUN_ONLY = 1
    PIUPARTS_FAIL_ON_ERROR = 2
    PIUPARTS_FAIL_ON_WARNING = 3
    PIUPARTS_CHOICES = (
        (PIUPARTS_DISABLED,        "Don't run piuparts"),
        (PIUPARTS_RUN_ONLY,        "Run piuparts"),
        (PIUPARTS_FAIL_ON_ERROR,   "Run piuparts and fail on errors"),
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
            ("Basics", {
                    "fields": ("base_source", "extra_sources", "components")
                    }),
            ("Architectures", {
                    "fields": ("mandatory_architectures", "optional_architectures", "architecture_all")
                    }),
            ("Build options", {
                    "fields": ("build_dep_resolver", "apt_allow_unauthenticated", "lintian_mode", "lintian_extra_options")
                    }),
            ("Extra", {
                    "classes": ("collapse",),
                    "fields": ("chroot_setup_script", "sbuildrc_snippet")
                    }),)

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

    notify = django.db.models.ManyToManyField(EmailAddress, blank=True,
                                              help_text="Arbitary list of email addresses to notify.")
    notify_changed_by = django.db.models.BooleanField(default=False,
                                                      help_text="Notify the address in the 'Changed-By' field of the uploaded changes file.")
    notify_maintainer = django.db.models.BooleanField(default=False,
                                                      help_text="Notify the address in the 'Maintainer' field of the uploaded changes file.")

    external_home_url = django.db.models.URLField(blank=True)

    class Meta(StatusModel.Meta):
        verbose_name_plural = "Repositories"

    class Admin(StatusModel.Admin):
        fieldsets = (
            ("Basics", {
                    "fields": ("identity", "layout", "distributions")
                    }),
            ("Notify and extra options", {
                    "fields": ("notify", "notify_changed_by", "notify_maintainer", "external_home_url")
                    }),)

    def __init__(self, *args, **kwargs):
        super(Repository, self).__init__(*args, **kwargs)
        log.debug("Initializing repository '{identity}'".format(identity=self.identity))

        self.mbd_uploadable_distributions = []
        for d in self.distributions.all():
            for s in self.layout.suites.all():
                if s.migrates_from == None:
                    self.mbd_uploadable_distributions.append("{d}-{identity}-{s}".format(
                            identity=self.identity,
                            d=d.base_source.codename,
                            s=s.name))

        self._reprepro = reprepro.Reprepro(self)

    def __unicode__(self):
        return self.identity

    def mbd_get_path(self):
        return os.path.join(setup.REPOSITORIES_DIR, self.identity)

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
        from mini_buildd import daemon
        return "deb {u}/{r}/{i}/ {d} {c}".format(
            u=daemon.get().model.mbd_get_ftp_url(),
            r=os.path.basename(setup.REPOSITORIES_DIR),
            i=self.identity, d=self.mbd_get_dist(dist, suite), c=self.mbd_get_components())

    def mbd_find_dist(self, dist):
        base, identity, suite = misc.parse_distribution(dist)
        log.debug("Finding dist for {d}: Base={b}, RepoId={r}, Suite={s}".format(d=dist, b=base, r=identity, s=suite))

        if identity == self.identity:
            for d in self.distributions.all():
                if d.base_source.codename == base:
                    for s in self.layout.suites.all():
                        if s.name == suite:
                            return d,s
        raise Exception("No such distribution in repository {i}: {d}".format(self.identity, d=dist))

    def mbd_get_apt_sources_list(self, dist):
        """
        .. todo::

        - get_apt_sources_list(): decide what other mini-buildd suites are to be included automatically
        """
        d,s = self.mbd_find_dist(dist)
        res = d.mbd_get_apt_sources_list()
        res += "\n"
        res += "# Mini-Buildd: {d}\n".format(d=dist)
        res += self.mbd_get_apt_line(d, s)
        return res

    def mbd_get_apt_preferences(self):
        ".. todo:: STUB"
        return ""

    def mbd_get_apt_keys(self, dist):
        d,s = self.mbd_find_dist(dist)
        from mini_buildd import daemon
        result = daemon.get().model.mbd_get_pub_key()
        for e in d.extra_sources.all():
            result += e.source.apt_key
        return result

    def mbd_get_chroot_setup_script(self, dist):
        d,s = self.mbd_find_dist(dist)
        # Note: For some reason (python, django sqlite, browser?) the text field may be in DOS mode.
        return misc.fromdos(d.chroot_setup_script)

    def mbd_get_sbuildrc_snippet(self, dist, arch):
        d,s = self.mbd_find_dist(dist)
        libdir = os.path.join(setup.CHROOTS_DIR, d.base_source.codename, arch, setup.CHROOT_LIBDIR)

        # Note: For some reason (python, django sqlite, browser?) the text field may be in DOS mode.
        return misc.fromdos(misc.subst_placeholders(d.sbuildrc_snippet, { "LIBDIR": libdir }))

    def mbd_get_sources(self, dist, suite):
        result = ""
        result += "Base: " + str(dist.base_source) + "\n"
        for e in dist.extra_sources.all():
            result += "Extra: " + str(e) + "\n"
        return result

    def mbd_get_mandatory_version(self, dist, suite):
        return suite.get_mandatory_version(self, dist)

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
""".format(dist=self.mbd_get_dist(d, s),
           origin=self.mbd_get_origin(),
           components=self.mbd_get_components(),
           architectures=" ".join(d.mbd_get_all_architectures()),
           desc=self.mbd_get_desc(d, s),
           na="yes" if s.not_automatic else "no",
           bau="yes" if s.but_automatic_upgrades else "no"))

        return result.getvalue()

    def mbd_prepare(self, request):
        ".. todo:: README from 08x; please fix/update."
        from mini_buildd.models import msg_info

        path = self.mbd_get_path()
        msg_info(request, "Preparing repository: {identity} in '{path}'".format(identity=self.identity, path=path))

        misc.mkdirs(path)
        misc.mkdirs(os.path.join(path, "log"))
        misc.mkdirs(os.path.join(path, "chroots-update.d"))

        open(os.path.join(path, "README"), 'w').write("""
Automatically produced by mini-buildd on {date}.
Manual changes to this file are NOT preserved.

README for "~/.mini-buildd/": Place for local configuration

DO CHANGES ON THE REPOSITORY HOST ONLY. On builder-only hosts,
this directory is SYNCED from the repository host.

Preinstall hook
=====================================
Putting an executable file "preinstall" here will run this with
the full path to a "build" (i.e., all tests passed, to-be
installed) changes-file.

You may use this as temporary workaround to dput packages to
other repositories or to additionally use another package
manager like reprepro in parallel.

Base chroot maintenance customization
=====================================
Note that you only need any customization if you need to
apt-secure extra sources (for example bpo) or have other special
needs (like pre-seeding debconf variables).

 * "chroots-update.d/*.hook":
   What   : Custom hooks (shell snippets). Run in all base chroots as root (!).
   Used by: mbd-update-bld.
""".format(date=datetime.datetime.now()))

        # Reprepro config
        self._reprepro.prepare()

    def mbd_unprepare(self, request):
        raise Exception("Not implemented: Can't remove repo from system yet")

django.contrib.admin.site.register(Repository, Repository.Admin)
