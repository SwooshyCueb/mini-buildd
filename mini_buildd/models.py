# -*- coding: utf-8 -*-
import socket
import StringIO
import os
import datetime

import GnuPGInterface

import django.db
import django.conf
import django.core.exceptions
import django.contrib
import logging

import mini_buildd
import mini_buildd.schroot

log = logging.getLogger(__name__)


class Mirror(django.db.models.Model):
    url = django.db.models.URLField(primary_key=True, max_length=512,
                          default="http://ftp.debian.org/debian",
                          help_text="The URL of an apt mirror/repository")

    class Meta:
        ordering = ['url']

    def __unicode__(self):
        return self.url

    class Admin(django.contrib.admin.ModelAdmin):
        search_fields = ['url']


class Source(django.db.models.Model):
    origin = django.db.models.CharField(max_length=100, default="Debian")
    codename = django.db.models.CharField(max_length=100, default="sid")
    mirrors = django.db.models.ManyToManyField('Mirror')

    class Meta:
        unique_together = ('origin', 'codename')
        ordering = ['origin', 'codename']

    def get_mirror(self):
        ".. todo:: Returning first mirror only. Should return preferred/working one from mirror list."
        for m in self.mirrors.all():
            return m

    def get_apt_line(self, components="main contrib non-free"):
        m = self.get_mirror()
        return "deb {u} {d} {C}".format(u=m.url, d=self.codename, C=components)

    def get_apt_pin(self):
        return "release n=" + self.codename + ", o=" + self.origin

    def __unicode__(self):
        return self.origin + ": " + self.codename + " [" + self.get_apt_pin() + "]"

    class Admin(django.contrib.admin.ModelAdmin):
        search_fields = ['origin', 'codename']


class PrioritisedSource(django.db.models.Model):
    source = django.db.models.ForeignKey(Source)
    prio = django.db.models.IntegerField(default=1,
                               help_text="A apt pin priority value (see 'man apt_preferences')."
                               "Examples: 1=not automatic, 1001=downgrade'")

    class Meta:
        unique_together = ('source', 'prio')

    def __unicode__(self):
        return self.source.__unicode__() + ": Prio=" + str(self.prio)


class Architecture(django.db.models.Model):
    arch = django.db.models.CharField(primary_key=True, max_length=50,
                            help_text="A valid Debian architecture (the output of 'dpkg --print-architecture' on the architecture)."
                            "Examples: 'i386', 'amd64', 'powerpc'")

    def __unicode__(self):
        return self.arch


class Suite(django.db.models.Model):
    name = django.db.models.CharField(
        primary_key=True, max_length=50,
        help_text="A suite to support, usually s.th. like 'unstable','testing' or 'stable'.")
    mandatory_version = django.db.models.CharField(
        max_length=50, default="~{rid}{nbv}+[1-9]",
        help_text="Mandatory version template; {rid}=repository id, {nbv}=numerical base distribution version.")

    migrates_from = django.db.models.ForeignKey('self', blank=True, null=True,
                                      help_text="Leave this blank to make this suite uploadable, or chose a suite where this migrates from.")
    not_automatic = django.db.models.BooleanField(default=True)
    but_automatic_upgrades = django.db.models.BooleanField(default=False)

    def __unicode__(self):
        return self.name + " (" + ("<= " + self.migrates_from.name if self.migrates_from else "uploadable") + ")"


class Layout(django.db.models.Model):
    name = django.db.models.CharField(primary_key=True, max_length=128,
                            help_text="Name for the layout.")
    suites = django.db.models.ManyToManyField(Suite)

    def __unicode__(self):
        return self.name

def create_default_layout():
    l=Layout(name="Default")
    l.save()
    e=Suite(name="experimental", mandatory_version="~{rid}{nbv}+0")
    e.save()
    l.suites.add(e)

    u=Suite(name="unstable")
    u.save()
    l.suites.add(u)

    t=Suite(name="testing", migrates_from=u)
    t.save()
    l.suites.add(t)

    s=Suite(name="stable", migrates_from=t)
    s.save()
    l.suites.add(s)
    return l

class Distribution(django.db.models.Model):
    # @todo: limit to distribution?  limit_choices_to={'codename': 'sid'})
    base_source = django.db.models.ForeignKey(Source, primary_key=True)
    # @todo: how to limit to source.kind?
    extra_sources = django.db.models.ManyToManyField(PrioritisedSource, blank=True, null=True)

    def get_apt_sources_list(self):
        res = "# Base: {p}\n".format(p=self.base_source.get_apt_pin())
        res += self.base_source.get_apt_line() + "\n\n"
        for e in self.extra_sources.all():
            res += "# Extra: {p}\n".format(p=e.source.get_apt_pin())
            res += e.source.get_apt_line() + "\n"
        return res

    def __unicode__(self):
        # @todo: somehow indicate extra sources to visible name
        return self.base_source.origin + ": " + self.base_source.codename

class Repository(django.db.models.Model):
    id = django.db.models.CharField(primary_key=True, max_length=50, default=socket.gethostname())
    host = django.db.models.CharField(max_length=100, default=socket.getfqdn())

    layout = django.db.models.ForeignKey(Layout)
    dists = django.db.models.ManyToManyField(Distribution)
    archs = django.db.models.ManyToManyField(Architecture)
    arch_all = django.db.models.ForeignKey(Architecture, related_name="ArchitectureAll")

    gnupg_template = django.db.models.TextField(default="""
Key-Type: DSA
Key-Length: 1024
Subkey-Type: ELG-E
Subkey-Length: 1024
Expire-Date: 0""")

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

        self.gnupg = GnuPGInterface.GnuPG()
        self.gnupg.options.meta_interactive = 0
        self.gnupg.options.homedir = os.path.join(self.get_path(), ".gnupg")

        # @todo: to be replaced in template; Only as long as we dont know better
        self.pgp_key_ascii = self.getGpgPubKey()

        self.uploadable_dists = []
        for d in self.dists.all():
            for s in self.layout.suites.all():
                if s.migrates_from == None:
                    self.uploadable_dists.append("{d}-{id}-{s}".format(
                            id=self.id,
                            d=d.base_source.codename,
                            s=s.name))

        self._reprepro = mini_buildd.Reprepro(self)

    def __unicode__(self):
        return self.id

    def get_path(self):
        return os.path.join(django.conf.settings.MINI_BUILDD_HOME, "repositories", self.id)

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
            archs.append(a.arch)
        return archs

    def get_desc(self, dist, suite):
        return "{d} {s} packages for {id}".format(id=self.id, d=dist.base_source.codename, s=suite.name)

    def get_apt_line(self, dist, suite):
        return "deb ftp://{h}:8067/repositories/{id}/ {dist} {components}".format(
            h=self.host, id=self.id, dist=self.get_dist(dist, suite), components=self.get_components())

    def get_apt_sources_list(self, dist):
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
                        ".. todo:: decide what other mini-buildd suites are to be included automatically"
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
        return suite.mandatory_version.format(rid=self.id, nbv=mini_buildd.misc.codename2Version(dist.base_source.codename))

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

    def getGpgPubKey(self):
        result = ""
        try:
            # Always update the ascii armored public key
            proc = self.gnupg.run(["--armor", "--export=mini-buildd-{id}@{h}".format(id=self.id, h=self.host)],
                                  create_fhs=['stdin', 'stdout', 'stderr'])
            report = proc.handles['stderr'].read()
            proc.handles['stderr'].close()
            result = proc.handles['stdout'].read()
            proc.wait()
        except:
            log.warn("No GNUPG pub key found.")
            result = ""
        return result

    def prepareGnuPG(self):
        if self.getGpgPubKey():
            log.info("GPG public key found, skipping key generation...")
        else:
            log.info("Generating new Gnu PG key in '{h}'.".format(h=self.get_path()))
            proc = self.gnupg.run(["--gen-key"],
                                  create_fhs=['stdin', 'stdout', 'stderr'])

            proc.handles['stdin'].write('''{tpl}
Name-Real: mini-buildd-{id} on {h}
Name-Email: mini-buildd-{id}@{h}
'''.format(tpl=self.gnupg_template, id=self.id, h=self.host))

            log.debug("Generating gnupg key...")
            proc.handles['stdin'].close()
            report = proc.handles['stderr'].read()
            proc.handles['stderr'].close()
            try:
                proc.wait()
            except:
                log.error(report)
                raise

    def prepare(self):
        path = self.get_path()
        log.info("Preparing repository: {id} in '{path}'".format(id=self.id, path=path))

        mini_buildd.misc.mkdirs(path)
        self.prepareGnuPG()
        mini_buildd.misc.mkdirs(os.path.join(path, "log"))
        mini_buildd.misc.mkdirs(os.path.join(path, "apt-secure.d"))
        open(os.path.join(path, "apt-secure.d", "auto-mini-buildd.key"), 'w').write(self.getGpgPubKey())
        mini_buildd.misc.mkdirs(os.path.join(path, "debconf-preseed.d"))
        mini_buildd.misc.mkdirs(os.path.join(path, "chroots-update.d"))

        # @todo This 08x README; please fix.
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


class Builder(django.db.models.Model):
    arch = django.db.models.ForeignKey(Architecture, primary_key=True)
    dists = django.db.models.ManyToManyField(Distribution)

    SCHROOT_MODES = (
        ('lvm_loop', 'LVM via loop device'),
    )
    schroot_mode = django.db.models.CharField(max_length=20, choices=SCHROOT_MODES, default="lvm_loop")

    max_parallel_builds = django.db.models.IntegerField(default=4,
                                   help_text="Maximum number of parallel builds.")

    sbuild_parallel = django.db.models.IntegerField(default=1,
                                   help_text="Degree of parallelism per build.")

    def get_path(self):
        return os.path.join(django.conf.settings.MINI_BUILDD_HOME, "builders", self.arch.arch)

    def prepare(self):
        log.debug("Preparing '{m}' builder for '{a}'".format(m=self.schroot_mode, a=self.arch))
        s = mini_buildd.schroot.Schroot(self)
        s.prepare()

    def __unicode__(self):
        return "Builder for " + self.arch.arch


class Remote(django.db.models.Model):
    host = django.db.models.CharField(max_length=99, default=socket.getfqdn())

    def __unicode__(self):
        return "Remote: " + self.host


def create_default(mirror):
    codename = mini_buildd.misc.get_cmd_stdout("lsb_release --short --codename").strip()
    arch = mini_buildd.misc.get_cmd_stdout("dpkg --print-architecture").strip()

    log.info("Creating default config: {c}:{a} from '{m}'".format(c=codename, a=arch, m=mirror))

    m=Mirror(url=mirror)
    m.save()

    s=Source(codename=codename)
    s.save()
    s.mirrors.add(m)
    s.save()

    d=Distribution(base_source=s)
    d.save()

    a=Architecture(arch=arch)
    a.save()

    l=create_default_layout()
    l.save()

    r=Repository(layout=l, arch_all=a)
    r.save()
    r.archs.add(a)
    r.dists.add(d)
    r.save()

    b=Builder(arch=a)
    b.dists.add(d)
    b.save()
