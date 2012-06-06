# -*- coding: utf-8 -*-
import StringIO, os, re, datetime, socket, logging

import django.db

from mini_buildd import setup, misc, reprepro

log = logging.getLogger(__name__)

from mini_buildd.models import Distribution
from mini_buildd.models import Architecture
from mini_buildd.models import Layout
class Repository(django.db.models.Model):
    class Meta():
        verbose_name_plural = "Repositories"

    id = django.db.models.CharField(primary_key=True, max_length=50, default=socket.gethostname())
    host = django.db.models.CharField(max_length=100, default=socket.getfqdn())

    layout = django.db.models.ForeignKey(Layout)
    dists = django.db.models.ManyToManyField(Distribution)
    archs = django.db.models.ManyToManyField(Architecture)
    arch_all = django.db.models.ForeignKey(Architecture, related_name="ArchitectureAll")

    RESOLVERS = (('apt',       "apt resolver"),
                 ('aptitude',  "aptitude resolver"),
                 ('internal',  "internal resolver"))
    build_dep_resolver = django.db.models.CharField(max_length=10, choices=RESOLVERS, default="apt")

    apt_allow_unauthenticated = django.db.models.BooleanField(default=False)

    LINTIAN_MODES = (('disabled',        "Don't run lintian"),
                     ('never-fail',      "Run lintian and show results"),
                     ('fail-on-error',   "Run lintian and fail on errors"),
                     ('fail-on-warning', "Run lintian and ail on warnings"))
    lintian_mode = django.db.models.CharField(max_length=20, choices=LINTIAN_MODES, default="fail-on-error")
    lintian_extra_options = django.db.models.CharField(max_length=200, default="--info")

    mail = django.db.models.EmailField(blank=True)
    extdocurl = django.db.models.URLField(blank=True)

    def __init__(self, *args, **kwargs):
        super(Repository, self).__init__(*args, **kwargs)
        log.debug("Initializing repository '{id}'".format(id=self.id))

        self.uploadable_dists = []
        for d in self.dists.all():
            for s in self.layout.suites.all():
                if s.migrates_from == None:
                    self.uploadable_dists.append("{d}-{id}-{s}".format(
                            id=self.id,
                            d=d.base_source.codename,
                            s=s.name))

        self._reprepro = reprepro.Reprepro(self)

    def __unicode__(self):
        return self.id

    def get_path(self):
        return os.path.join(setup.REPOSITORIES_DIR, self.id)

    def get_incoming_path(self):
        return os.path.join(self.get_path(), "incoming")


    def get_dist(self, dist, suite):
        return dist.base_source.codename + "-" + self.id + "-" + suite.name

    def get_origin(self):
        return "mini-buildd" + self.id

    def get_components(self):
        return "main contrib non-free"

    def get_archs(self):
        archs = []
        for a in self.archs.all():
            archs.append(a.name)
        return archs

    def get_desc(self, dist, suite):
        return "{d} {s} packages for {id}".format(id=self.id, d=dist.base_source.codename, s=suite.name)

    def get_apt_line(self, dist, suite):
        return "deb ftp://{h}:8067/{r}/{id}/ {dist} {components}".format(
            h=self.host, r=os.path.basename(setup.REPOSITORIES_DIR),
            id=self.id, dist=self.get_dist(dist, suite), components=self.get_components())

    def get_apt_sources_list(self, dist):
        ".. todo:: decide what other mini-buildd suites are to be included automatically"
        dist_split = dist.split("-")
        base = dist_split[0]
        id = dist_split[1]
        suite = dist_split[2]
        log.debug("Sources list for {d}: Base={b}, RepoId={r}, Suite={s}".format(d=dist, b=base, r=id, s=suite))

        for d in self.dists.all():
            if d.base_source.codename == base:
                res = d.get_apt_sources_list()
                res += "\n"
                for s in self.layout.suites.all():
                    if s.name == suite:
                        res += "# Mini-Buildd: {d}\n".format(d=dist)
                        res += self.get_apt_line(d, s)
                        return res

        raise Exception("Could not produce sources.list")

    def get_apt_preferences(self):
        ".. todo:: STUB"
        return ""

    def get_sources(self, dist, suite):
        result = ""
        result += "Base: " + str(dist.base_source) + "\n"
        for e in dist.extra_sources.all():
            result += "Extra: " + str(e) + "\n"
        return result

    def get_mandatory_version(self, dist, suite):
        return suite.mandatory_version.format(rid=self.id, nbv=misc.codename2Version(dist.base_source.codename))

    def repreproConfig(self):
        result = StringIO.StringIO()
        for d in self.dists.all():
            for s in self.layout.suites.all():
                result.write("""
Codename: {dist}
Suite:  {dist}
Label: {dist}
Origin: {origin}
Components: {components}
Architectures: source {archs}
Description: {desc}
SignWith: default
NotAutomatic: {na}
ButAutomaticUpgrades: {bau}
""".format(dist=self.get_dist(d, s),
           origin=self.get_origin(),
           components=self.get_components(),
           archs=" ".join(self.get_archs()),
           desc=self.get_desc(d, s),
           na="yes" if s.not_automatic else "no",
           bau="yes" if s.but_automatic_upgrades else "no"))

        return result.getvalue()

    def prepare(self):
        ".. todo:: README from 08x; please fix/update."

        path = self.get_path()
        log.info("Preparing repository: {id} in '{path}'".format(id=self.id, path=path))

        misc.mkdirs(path)
        misc.mkdirs(os.path.join(path, "log"))
        misc.mkdirs(os.path.join(path, "apt-secure.d"))
        open(os.path.join(path, "apt-secure.d", "auto-mini-buildd.key"), 'w').write("OBSOLETE")
        misc.mkdirs(os.path.join(path, "debconf-preseed.d"))
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

 * "apt-secure.d/*.key":
   What   : Apt-secure custom keys for extra sources; keys are added to all base chroots.
   Used by: mbd-update-bld (/usr/share/mini-buildd/chroots-update.d/05_apt-secure).
   Note   : Don't touch auto-generated key 'auto-mini-buildd.key'.
 * "debconf-preseed.d/*.conf":
   What   : Pre-defined values for debconf (see debconf-set-selections).
   Used by: mbd-update-bld (/usr/share/mini-buildd/chroots-update.d/20_debconf-preseed).
   Note   : One noteable use case are licenses from non-free like in the sun-java packages.
 * "chroots-update.d/*.hook":
   What   : Custom hooks (shell snippets). Run in all base chroots as root (!).
   Used by: mbd-update-bld.
""".format(date=datetime.datetime.now()))

        # Reprepro config
        self._reprepro.prepare()

django.contrib.admin.site.register(Repository)
