# -*- coding: utf-8 -*-
import StringIO, os, re, datetime, socket, logging

import django.db

from mini_buildd import setup, misc, reprepro

log = logging.getLogger(__name__)

from mini_buildd.models import EmailAddress, StatusModel, Architecture, Source, PrioSource, Component, msg_info, msg_warn, msg_error

class Suite(django.db.models.Model):
    name = django.db.models.CharField(
        primary_key=True, max_length=50,
        help_text="A suite to support, usually s.th. like 'unstable','testing' or 'stable'.")
    mandatory_version = django.db.models.CharField(
        max_length=50, default="~{rid}{nbv}+[1-9]",
        help_text="Mandatory version template; {rid}=repository id, {nbv}=numerical base distribution version.")

    migrates_from = django.db.models.ForeignKey(
        'self', blank=True, null=True,
        help_text="Leave this blank to make this suite uploadable, or chose a suite where this migrates from.")
    not_automatic = django.db.models.BooleanField(default=True)
    but_automatic_upgrades = django.db.models.BooleanField(default=False)

    class Meta:
        verbose_name = "[B1] Suite"

    def __unicode__(self):
        return self.name + " (" + ("<= " + self.migrates_from.name if self.migrates_from else "uploadable") + ")"

django.contrib.admin.site.register(Suite)


class Layout(django.db.models.Model):
    name = django.db.models.CharField(primary_key=True, max_length=128,
                            help_text="Name for the layout.")
    suites = django.db.models.ManyToManyField(Suite)

    class Meta:
        verbose_name = "[B2] Layout"

    def __unicode__(self):
        return self.name

django.contrib.admin.site.register(Layout)


class Distribution(django.db.models.Model):
    base_source = django.db.models.ForeignKey(Source)
    extra_sources = django.db.models.ManyToManyField(PrioSource, blank=True)
    components = django.db.models.ManyToManyField(Component)

    chroot_setup_script = django.db.models.TextField(blank=True,
                                                     help_text="""\
Script that will be run via sbuild's '--chroot-setup-command'.
<br/>
Example:
<pre>
#!/bin/sh -e

# Install these additional packages
apt-get install ccache

# Accept sun-java6 licence so we can build-depend on it
echo "sun-java6-bin shared/accepted-sun-dlj-v1-1  boolean true" | debconf-set-selections --verbose
echo "sun-java6-jdk shared/accepted-sun-dlj-v1-1  boolean true" | debconf-set-selections --verbose
echo "sun-java6-jre shared/accepted-sun-dlj-v1-1  boolean true" | debconf-set-selections --verbose

# Workaround for Debian Bug #327477 (bash building)
[ -e /dev/fd ] || ln -sv /proc/self/fd /dev/fd
[ -e /dev/stdin ] || ln -sv fd/0 /dev/stdin
[ -e /dev/stdout ] || ln -sv fd/1 /dev/stdout
[ -e /dev/stderr ] || ln -sv fd/2 /dev/stderr
</pre>
""")

    class Meta:
        verbose_name = "[B3] Distribution"

    class Admin(django.contrib.admin.ModelAdmin):
        fieldsets = (
            ("Basics", {
                    "fields": ("base_source", "extra_sources", "components")
                    }),
            ("Extra", {
                    "classes": ("collapse",),
                    "fields": ("chroot_setup_script",)
                    }),)

    def __unicode__(self):
        def xtra():
            result = ""
            for e in self.extra_sources.all():
                result += "+ " + e.mbd_id()
            return result

        def cmps():
            result = ""
            for c in self.components.all():
                result += c.name + " "
            return result

        return "{b} {e} [{c}]".format(b=self.base_source.mbd_id(), e=xtra(), c=cmps())

    def mbd_get_apt_sources_list(self):
        res = "# Base: {p}\n".format(p=self.base_source.mbd_get_apt_pin())
        res += self.base_source.mbd_get_apt_line() + "\n\n"
        for e in self.extra_sources.all():
            res += "# Extra: {p}\n".format(p=e.source.mbd_get_apt_pin())
            res += e.source.mbd_get_apt_line() + "\n"
        return res


django.contrib.admin.site.register(Distribution, Distribution.Admin)

class Repository(StatusModel):
    id = django.db.models.CharField(primary_key=True, max_length=50, default=socket.gethostname())

    layout = django.db.models.ForeignKey(Layout)
    distributions = django.db.models.ManyToManyField(Distribution)
    architectures = django.db.models.ManyToManyField(Architecture)
    architecture_all = django.db.models.ForeignKey(Architecture, related_name="ArchitectureAll")

    RESOLVERS = (('apt',       "apt resolver"),
                 ('aptitude',  "aptitude resolver"),
                 ('internal',  "internal resolver"))
    build_dep_resolver = django.db.models.CharField(max_length=10, choices=RESOLVERS, default="apt")

    apt_allow_unauthenticated = django.db.models.BooleanField(default=False)

    LINTIAN_MODES = (('disabled',        "Don't run lintian"),
                     ('never-fail',      "Run lintian"),
                     ('fail-on-error',   "Run lintian and fail on errors"),
                     ('fail-on-warning', "Run lintian and fail on warnings"))
    lintian_mode = django.db.models.CharField(max_length=20, choices=LINTIAN_MODES, default="fail-on-error")
    lintian_extra_options = django.db.models.CharField(max_length=200, default="--info")

    mail_notify = django.db.models.ManyToManyField(EmailAddress, blank=True)
    extdocurl = django.db.models.URLField(blank=True)

    class Meta(StatusModel.Meta):
        verbose_name = "[B4] Repository"
        verbose_name_plural = "[B4] Repositories"

    class Admin(StatusModel.Admin):
        fieldsets = (
            ("Basics", {
                    "fields": ("id", "layout", "distributions", "architectures")
                    }),
            ("Build options", {
                    "fields": ("architecture_all", "build_dep_resolver", "apt_allow_unauthenticated", "lintian_mode", "lintian_extra_options")
                    }),
            ("Extra", {
                    "classes": ("collapse",),
                    "fields": ("mail_notify", "extdocurl")
                    }),)

    def __init__(self, *args, **kwargs):
        super(Repository, self).__init__(*args, **kwargs)
        log.debug("Initializing repository '{id}'".format(id=self.id))

        self.mbd_uploadable_distributions = []
        for d in self.distributions.all():
            for s in self.layout.suites.all():
                if s.migrates_from == None:
                    self.mbd_uploadable_distributions.append("{d}-{id}-{s}".format(
                            id=self.id,
                            d=d.base_source.codename,
                            s=s.name))

        self._reprepro = reprepro.Reprepro(self)

    def __unicode__(self):
        return self.id

    def mbd_get_path(self):
        return os.path.join(setup.REPOSITORIES_DIR, self.id)

    def mbd_get_incoming_path(self):
        return os.path.join(self.mbd_get_path(), "incoming")

    def mbd_get_dist(self, dist, suite):
        return dist.base_source.codename + "-" + self.id + "-" + suite.name

    def mbd_get_origin(self):
        return "mini-buildd" + self.id

    def mbd_get_components(self):
        return "main contrib non-free"

    def mbd_get_architectures(self):
        architectures = []
        for a in self.architectures.all():
            architectures.append(a.name)
        return architectures

    def mbd_get_desc(self, dist, suite):
        return "{d} {s} packages for {id}".format(id=self.id, d=dist.base_source.codename, s=suite.name)

    def mbd_get_apt_line(self, dist, suite):
        from mini_buildd import daemon
        return "deb ftp://{h}:{p}/{r}/{id}/ {dist} {components}".format(
            h=daemon.get().fqdn, p=8067, r=os.path.basename(setup.REPOSITORIES_DIR),
            id=self.id, dist=self.mbd_get_dist(dist, suite), components=self.mbd_get_components())

    def mbd_get_apt_sources_list(self, dist):
        """
        .. todo::

        - get_apt_sources_list(): decide what other mini-buildd suites are to be included automatically
        - this and next four funcs: clean up code style && redundancies.
        """
        dist_split = dist.split("-")
        base = dist_split[0]
        id = dist_split[1]
        suite = dist_split[2]
        log.debug("Sources list for {d}: Base={b}, RepoId={r}, Suite={s}".format(d=dist, b=base, r=id, s=suite))

        for d in self.distributions.all():
            if d.base_source.codename == base:
                res = d.mbd_get_apt_sources_list()
                res += "\n"
                for s in self.layout.suites.all():
                    if s.name == suite:
                        res += "# Mini-Buildd: {d}\n".format(d=dist)
                        res += self.mbd_get_apt_line(d, s)
                        return res

        raise Exception("Could not produce sources.list")

    def mbd_get_apt_preferences(self):
        ".. todo:: STUB"
        return ""

    def mbd_get_apt_keys(self, dist):
        dist_split = dist.split("-")
        base = dist_split[0]
        id = dist_split[1]
        suite = dist_split[2]
        log.debug("Sources list for {d}: Base={b}, RepoId={r}, Suite={s}".format(d=dist, b=base, r=id, s=suite))

        for d in self.distributions.all():
            if d.base_source.codename == base:
                from mini_buildd import daemon
                result = daemon.get().mbd_get_pub_key()
                for e in d.extra_sources.all():
                    result += e.source.apt_key
                return result
        raise Exception("Could not produce apt keys")

    def mbd_get_chroot_setup_script(self, dist):
        dist_split = dist.split("-")
        base = dist_split[0]
        id = dist_split[1]
        suite = dist_split[2]
        log.debug("Sources list for {d}: Base={b}, RepoId={r}, Suite={s}".format(d=dist, b=base, r=id, s=suite))

        for d in self.distributions.all():
            if d.base_source.codename == base:
                # Note: For some reason (python, django sqlite, browser?) the text field may be in DOS mode.
                return d.chroot_setup_script.replace('\r\n', '\n').replace('\r', '')
        raise Exception("Could not find dist")

    def mbd_get_sources(self, dist, suite):
        result = ""
        result += "Base: " + str(dist.base_source) + "\n"
        for e in dist.extra_sources.all():
            result += "Extra: " + str(e) + "\n"
        return result

    def mbd_get_mandatory_version(self, dist, suite):
        return suite.mandatory_version.format(rid=self.id, nbv=misc.codename2Version(dist.base_source.codename))

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
           architectures=" ".join(self.mbd_get_architectures()),
           desc=self.mbd_get_desc(d, s),
           na="yes" if s.not_automatic else "no",
           bau="yes" if s.but_automatic_upgrades else "no"))

        return result.getvalue()

    def mbd_prepare(self, request):
        ".. todo:: README from 08x; please fix/update."
        from mini_buildd.models import msg_info

        path = self.mbd_get_path()
        msg_info(request, "Preparing repository: {id} in '{path}'".format(id=self.id, path=path))

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
