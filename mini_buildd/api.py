# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import copy
import logging

import mini_buildd.misc

LOG = logging.getLogger(__name__)


class Command(object):
    COMMAND = None

    # Auth
    NONE = 0
    LOGIN = 1
    STAFF = 2
    ADMIN = 3
    AUTH = NONE

    CONFIRM = False
    NEEDS_RUNNING_DAEMON = False
    ARGUMENTS = []

    COMMON_ARG_VERSION = (["--version", "-V"], {"action": "store", "metavar": "VERSION",
                                                "default": "",
                                                "help": """
limit command to that version. Use it for the rare case of
multiple version of the same package in one distribution (in
different components), or just as safeguard
"""})

    @classmethod
    def _filter_api_args(cls, args, args_help, set_if_missing=False):
        def _get(key):
            try:
                # django request.GET args
                return ",".join(args.getlist(key))
            except:
                # dict arg (like from get_default_args)
                return args[key]

        result = {}
        for sargs, kvsargs in cls.ARGUMENTS:
            # Sanitize args
            # '--with-xyz' -> 'with_xyz'
            arg = sargs[0].replace("--", "", 1).replace("-", "_")
            if arg in args:
                result[arg] = _get(arg)

            elif "default" in kvsargs:
                result[arg] = kvsargs["default"]
            elif set_if_missing:
                result[arg] = arg.upper()

            # Helper to access help via django templates
            args_help[arg] = kvsargs.get("help")

            # Check required
            if sargs[0][:2] != "--" or ("required" in kvsargs and kvsargs["required"]):
                if arg not in result or not result[arg]:
                    raise Exception("Missing required argument '{a}'".format(a=arg))

        return result

    @classmethod
    def get_default_args(cls):
        dummy = {}
        return cls._filter_api_args({}, dummy, set_if_missing=True)

    def __init__(self, args, request=None, msglog=LOG):
        self.args_help = {}
        self.args = self._filter_api_args(args, self.args_help)
        self.request = request
        self.msglog = msglog
        self._plain_result = ""

    def __getstate__(self):
        "Log object cannot be pickled."
        pstate = copy.copy(self.__dict__)
        del pstate["msglog"]
        del pstate["request"]
        return pstate

    def __unicode__(self):
        return self._plain_result

    @classmethod
    def docstring(cls):
        return cls.__doc__

    def has_flag(self, flag):
        return self.args.get(flag, "False") == "True"

    def arg_false2none(self, key):
        value = self.args.get(key)
        return value if value else None


class Status(Command):
    """Show the status of the mini-buildd instance."""

    COMMAND = "status"

    def __init__(self, args, request=None, msglog=LOG):
        super(Status, self).__init__(args, request, msglog)

        self.version = "-1"
        self.http = ""
        self.ftp = ""
        self.running = False
        self.load = 0.0
        self.chroots = {}
        self.repositories = {}
        self.remotes = {}
        self.packaging = []
        self.building = []

    def run(self, daemon):
        # version string
        self.version = mini_buildd.__version__

        # hopo string
        self.http = daemon.model.mbd_get_http_hopo().string

        # hopo string
        self.ftp = daemon.model.mbd_get_ftp_hopo().string

        # bool
        self.running = daemon.is_running()

        # float value: 0 =< load <= 1+
        self.load = daemon.build_queue.load

        # chroots: {"squeeze": ["i386", "amd64"], "wheezy": ["amd64"]}
        for c in daemon.get_active_chroots():
            self.chroots.setdefault(c.source.codename, [])
            self.chroots[c.source.codename].append(c.architecture.name)

        # repositories: {"repo1": ["sid", "wheezy"], "repo2": ["squeeze"]}
        for r in daemon.get_active_repositories():
            self.repositories[r.identity] = [d.base_source.codename for d in r.distributions.all()]

        # remotes: ["host1.xyz.org:8066", "host2.xyz.org:8066"]
        self.remotes = [r.http for r in daemon.get_active_or_auto_reactivate_remotes()]

        # packaging/building: string/unicode
        self.packaging = ["{0}".format(p) for p in daemon.packages.values()]
        self.building = ["{0}".format(b) for b in daemon.builds.values()]

        self._plain_result = """\
http://{h} ({v}):

Daemon: {ds}: ftp://{f} (load {l})

Repositories: {r}
Chroots     : {c}
Remotes     : {rm}

Packager: {p_len} packaging
{p}
Builder: {b_len} building
{b}""".format(h=self.http,
              v=self.version,
              ds="UP" if self.running else "DOWN",
              f=self.ftp,
              l=self.load,
              r=self.repositories_str(),
              c=self.chroots_str(),
              rm=", ".join(self.remotes),
              p_len=len(self.packaging),
              p="\n".join(self.packaging) + "\n" if self.packaging else "",
              b_len=len(self.building),
              b="\n".join(self.building) + "\n" if self.building else "")

    def repositories_str(self):
        return ", ".join(["{i}: {c}".format(i=identity, c=" ".join(codenames)) for identity, codenames in self.repositories.items()])

    def chroots_str(self):
        return ", ".join(["{a}: {c}".format(a=arch, c=" ".join(codenames)) for arch, codenames in self.chroots.items()])

    def has_chroot(self, codename, arch):
        return codename in self.chroots and arch in self.chroots[codename]

    def __test_msglog(self):
        self.msglog.debug("DEBUG USER MESSAGE")
        self.msglog.info("INFO USER MESSAGE")
        self.msglog.warn("WARN USER MESSAGE")
        self.msglog.error("ERROR USER MESSAGE")
        self.msglog.critical("CRITICAL USER MESSAGE")


class Start(Command):
    """Start the Daemon (engine)."""
    COMMAND = "start"
    AUTH = Command.ADMIN
    ARGUMENTS = [
        (["--force-check", "-C"], {"action": "store_true",
                                   "default": False,
                                   "help": "run checks on instances even if already checked."})]

    def run(self, daemon):
        if not daemon.start(force_check=self.has_flag("force_check"), msglog=self.msglog):
            raise Exception("Could not start Daemon (check logs and messages).")
        self._plain_result = "{d}\n".format(d=daemon)


class Stop(Command):
    """Stop the Daemon (engine)."""
    COMMAND = "stop"
    AUTH = Command.ADMIN
    ARGUMENTS = []

    def run(self, daemon):
        if not daemon.stop(msglog=self.msglog):
            raise Exception("Could not stop Daemon (check logs and messages).")
        self._plain_result = "{d}\n".format(d=daemon)


class PrintUploaders(Command):
    """Print all GPG ids allowed to upload to repositories."""
    COMMAND = "printuploaders"
    AUTH = Command.ADMIN
    NEEDS_RUNNING_DAEMON = True
    ARGUMENTS = [
        (["--repository", "-R"], {"action": "store", "metavar": "REPO",
                                  "default": ".*",
                                  "help": "repository name regex."})]

    def _uploader_lines(self, daemon):
        for r in daemon.get_active_repositories().filter(identity__regex=r"^{r}$".format(r=self.args["repository"])):
            yield "Uploader keys for repository '{r}':".format(r=r.identity)
            if r.allow_unauthenticated_uploads:
                yield " WARNING: Unauthenticated uploads allowed anyway"
            for u in daemon.keyrings.get_uploaders()[r.identity].get_pub_colons():
                yield " {u}".format(u=u)

    def run(self, daemon):
        self._plain_result = "\n".join(self._uploader_lines(daemon)) + "\n"


class Meta(Command):
    """Call arbitrary meta functions for models; usually for internal use only."""
    COMMAND = "meta"
    AUTH = Command.ADMIN
    ARGUMENTS = [
        (["model"], {"help": "Model path, for example 'source.Archive'"}),
        (["function"], {"help": "Meta function to call, for example 'add_from_sources_list'"})]

    def run(self, daemon):
        daemon.meta(self.args["model"], self.args["function"], msglog=self.msglog)


class GetKey(Command):
    """Get GnuPG public key."""
    COMMAND = "getkey"

    def run(self, daemon):
        self._plain_result = daemon.model.mbd_get_pub_key()


class GetDputConf(Command):
    """Get recommended dput config snippet.

    Usually, this is for integration in your personal ~/.dput.cf.
    """
    COMMAND = "getdputconf"

    def run(self, daemon):
        self._plain_result = daemon.model.mbd_get_dput_conf()


class GetSourcesList(Command):
    """Get sources.list (apt lines).

    Usually, this output is put to a file like '/etc/sources.list.d/mini-buildd-xyz.list'.
    """
    COMMAND = "getsourceslist"
    ARGUMENTS = [
        (["codename"], {"help": "codename (base distribution) to get apt lines for"}),
        (["--repository", "-R"], {"action": "store", "metavar": "REPO",
                                  "default": ".*",
                                  "help": "repository name regex."}),
        (["--suite", "-S"], {"action": "store", "metavar": "SUITE",
                             "default": ".*",
                             "help": "suite name regex."}),
        (["--with-deb-src", "-s"], {"action": "store_true",
                                    "default": False,
                                    "help": "also list deb-src apt lines."}),
        (["--with-extra-sources", "-x"], {"action": "store_true",
                                          "default": False,
                                          "help": "also list extra sources needed."})]

    def run(self, daemon):
        self._plain_result = daemon.mbd_get_sources_list(self.args["codename"],
                                                         self.args["repository"],
                                                         self.args["suite"],
                                                         ["deb ", "deb-src "] if self.has_flag("with_deb_src") else ["deb "],
                                                         self.has_flag("with_extra_sources"))


class LogCat(Command):
    """Cat last n lines of the mini-buildd's log."""

    COMMAND = "logcat"
    AUTH = Command.STAFF
    ARGUMENTS = [
        (["--lines", "-n"], {"action": "store", "metavar": "N", "type": int,
                             "default": 500,
                             "help": "cat (approx.) the last N lines"})]

    def run(self, daemon):
        self._plain_result = daemon.logcat(lines=int(self.args["lines"]))


def _get_table_format(dct, cols):
    tlen = {}
    for _r, values in dict(dct).items():
        for value in values:
            for k, v in cols:
                if k in tlen:
                    tlen[k] = max(tlen[k], len(value[k]))
                else:
                    tlen[k] = max(len(v), len(value[k]))

    fmt = " | ".join(["{{{k}:{l}}}".format(k=k, l=tlen[k]) for k, v in cols])
    hdr = fmt.format(**dict(cols))
    fmt_tle = "{{t:^{l}}}".format(l=len(hdr))
    sep0 = "{{r:=^{l}}}".format(l=len(hdr)).format(r="")
    sep1 = "{{r:-^{l}}}".format(l=len(hdr)).format(r="")

    return (fmt, hdr, fmt_tle, sep0, sep1)


class List(Command):
    """List packages matching a shell-like glob pattern; matches both source and binary package names."""

    COMMAND = "list"
    AUTH = Command.LOGIN
    ARGUMENTS = [
        (["pattern"], {"help": "list source packages matching pattern"}),
        (["--with-rollbacks", "-r"], {"action": "store_true",
                                      "default": False,
                                      "help": "also list packages on rollback distributions"}),
        (["--distribution", "-D"], {"action": "store", "metavar": "DIST",
                                    "default": "",
                                    "help": "limit distributions to those matching this regex"}),
        (["--type", "-T"], {"action": "store", "metavar": "TYPE",
                            "default": "",
                            "help": "package type: dsc, deb or udeb (like reprepo --type)"})]

    def __init__(self, args, request=None, msglog=LOG):
        super(List, self).__init__(args, request, msglog)
        self.repositories = {}

    def run(self, daemon):
        # Save all results of all repos in a top-level dict (don't add repos with empty results).
        for r in daemon.get_active_repositories():
            r_result = r.mbd_package_list(self.args["pattern"],
                                          typ=self.arg_false2none("type"),
                                          with_rollbacks=self.has_flag("with_rollbacks"),
                                          dist_regex=self.args["distribution"])
            if r_result:
                self.repositories[r.identity] = r_result

    def __unicode__(self):
        if not self.repositories:
            return "No packages found."

        fmt, hdr, fmt_tle, sep0, sep1 = _get_table_format(self.repositories,
                                                          [("package", "Package"),
                                                           ("type", "Type"),
                                                           ("architecture", "Architecture"),
                                                           ("distribution", "Distribution"),
                                                           ("component", "Component"),
                                                           ("version", "Version"),
                                                           ("source", "Source")])

        def p_table(repository, values):
            return """\
{s0}
{t}
{s0}
{h}
{s1}
{p}
""".format(t=fmt_tle.format(t=" Repository '{r}' ".format(r=repository)),
           h=hdr,
           s0=sep0,
           s1=sep1,
           p="\n".join([fmt.format(**p) for p in values]))

        return "\n".join([p_table(k, v) for k, v in self.repositories.items()])


class Show(Command):
    """Show a source package."""

    COMMAND = "show"
    ARGUMENTS = [
        (["package"], {"help": "source package name"}),
        (["--verbose", "-v"], {"action": "store_true",
                               "default": False,
                               "help": "verbose output"})]

    def __init__(self, args, request=None, msglog=LOG):
        super(Show, self).__init__(args, request, msglog)
        # List of tuples: (repository, result)
        self.repositories = []

    def run(self, daemon):
        # Save all results of all repos in a top-level dict (don't add repos with empty results).
        for r in daemon.get_active_repositories():
            r_result = r.mbd_package_show(self.args["package"])
            if r_result:
                self.repositories.append((r, r_result))

    def __unicode__(self):
        if not self.repositories:
            return "No package found."

        def p_codename(codename, values):
            return """\
{s0}
{t}
{s0}
{h}
{s1}
{p}""".format(t=fmt_tle.format(t=" Basedist '{c}' ".format(c=codename)),
              h=hdr,
              s0=sep0,
              s1=sep1,
              p="\n".join([fmt.format(**p) for p in values]))

        rows = [("distribution", "Distribution"),
                ("sourceversion", "Version"),
                ("migrates_to", "Migrates to")]
        if self.has_flag("verbose"):
            rows.append(("dsc_url", "Source URL"))
            rows.append(("rollbacks_str_verbose", "Rollbacks"))
        else:
            rows.append(("rollbacks_str", "Rollbacks"))

        results = []
        for repository, codenames in self.repositories:
            # Add rollback_str
            for k, v in codenames:
                for d in v:
                    d["rollbacks_str"] = "{n}/{m}".format(n=len(d["rollbacks"]), m=d["rollback"])
                    d["rollbacks_str_verbose"] = d["rollbacks_str"] + \
                        ": " + " ".join(["{n}:{v}".format(n=r["no"], v=r["sourceversion"]) for r in d["rollbacks"]])

            fmt, hdr, fmt_tle, sep0, sep1 = _get_table_format(codenames, rows)
            results.append("{s}\n{t}\n".format(s=sep0, t=fmt_tle.format(t="Repository '{r}'".format(r=repository))) +
                           "\n".join([p_codename(k, v) for k, v in codenames]) +
                           "\n")
        return "\n".join(results)


class Migrate(Command):
    """Migrate a source package (along with all binary packages)."""

    COMMAND = "migrate"
    AUTH = Command.STAFF
    CONFIRM = True
    ARGUMENTS = [
        (["package"], {"help": "source package name"}),
        (["distribution"], {"help": "distribution to migrate from (if this is a '-rollbackN' distribution, this will perform a rollback restore)"}),
        Command.COMMON_ARG_VERSION]

    def run(self, daemon):
        repository, distribution, suite, rollback = daemon.parse_distribution(self.args["distribution"])
        self._plain_result = repository.mbd_package_migrate(self.args["package"],
                                                            distribution,
                                                            suite,
                                                            rollback=rollback,
                                                            version=self.arg_false2none("version"),
                                                            msglog=self.msglog)


class Remove(Command):
    """Remove a source package (along with all binary packages)."""

    COMMAND = "remove"
    AUTH = Command.ADMIN
    CONFIRM = True
    ARGUMENTS = [
        (["package"], {"help": "source package name"}),
        (["distribution"], {"help": "distribution to remove from"}),
        Command.COMMON_ARG_VERSION]

    def run(self, daemon):
        repository, distribution, suite, rollback = daemon.parse_distribution(self.args["distribution"])
        self._plain_result = repository.mbd_package_remove(self.args["package"],
                                                           distribution,
                                                           suite,
                                                           rollback=rollback,
                                                           version=self.arg_false2none("version"),
                                                           msglog=self.msglog)


class Port(Command):
    """Port an internal package.

    An internal 'port' is a no-changes (i.e., only the changelog
    will be adapted) rebuild of the given locally-installed
    package.
    """
    COMMAND = "port"
    AUTH = Command.STAFF
    NEEDS_RUNNING_DAEMON = True
    CONFIRM = True
    ARGUMENTS = [
        (["package"], {"help": "source package name"}),
        (["from_distribution"], {"help": "distribution to port from"}),
        (["to_distributions"], {"help": "comma-separated list of distributions to port to (when this equals the from-distribution, a rebuild will be done)"}),
        Command.COMMON_ARG_VERSION]

    def run(self, daemon):
        # Parse and pre-check all dists
        for to_distribution in self.args["to_distributions"].split(","):
            info = "Port {p}/{d} -> {to_d}".format(p=self.args["package"], d=self.args["from_distribution"], to_d=to_distribution)
            self.msglog.info("Trying: {i}".format(i=info))
            daemon.port(self.args["package"],
                        self.args["from_distribution"],
                        to_distribution,
                        version=self.arg_false2none("version"))
            self.msglog.info("Requested: {i}".format(i=info))
            self._plain_result += to_distribution + " "


class PortExt(Command):
    """Port an external package.

    An external 'port' is a no-changes (i.e., only the changelog
    will be adapted) rebuild of any given source package.
    """
    COMMAND = "portext"
    AUTH = Command.STAFF
    NEEDS_RUNNING_DAEMON = True
    CONFIRM = True
    ARGUMENTS = [
        (["dsc"], {"help": "URL of any Debian source package (dsc) to port"}),
        (["distributions"], {"help": "comma-separated list of distributions to port to"})]

    def run(self, daemon):
        # Parse and pre-check all dists
        for d in self.args["distributions"].split(","):
            info = "External port {dsc} -> {d}".format(dsc=self.args["dsc"], d=d)
            self.msglog.info("Trying: {i}".format(i=info))
            daemon.portext(self.args["dsc"], d)
            self.msglog.info("Requested: {i}".format(i=info))
            self._plain_result += d + " "


class Retry(Command):
    """Retry a previously failed package."""

    COMMAND = "retry"
    AUTH = Command.STAFF
    NEEDS_RUNNING_DAEMON = True
    CONFIRM = True
    ARGUMENTS = [
        (["package"], {"help": "source package name"}),
        (["version"], {"help": "source package's version"}),
        (["--repository", "-R"], {"action": "store", "metavar": "REPO",
                                  "default": "*",
                                  "help": "Repository name -- use only in case of multiple matches."})]

    def run(self, daemon):
        pkg_log = mini_buildd.misc.PkgLog(self.args["repository"], False, self.args["package"], self.args["version"])
        if not pkg_log.changes:
            raise Exception("No matching changes found for your retry query.")
        daemon.incoming_queue.put(pkg_log.changes)
        self.msglog.info("Retrying: {c}".format(c=os.path.basename(pkg_log.changes)))

        self._plain_result = os.path.basename(os.path.basename(pkg_log.changes))


class SetUserKey(Command):
    """Set a user's GnuPG public key."""

    COMMAND = "setuserkey"
    AUTH = Command.LOGIN
    CONFIRM = True
    ARGUMENTS = [
        (["key"], {"help": "GnuPG public key; multiline inputs will be handled as ascii armored full key, one-liners as key ids"})]

    def run(self, _daemon):
        uploader = self.request.user.uploader
        uploader.Admin.mbd_remove(self.request, uploader)
        key = self.args["key"]

        if "\n" in key:
            self.msglog.info("Using given key argument as full ascii-armored GPG key")
            uploader.key_id = ""
            uploader.key = key
        else:
            self.msglog.info("Using given key argument as key ID")
            uploader.key_id = key
            uploader.key = ""

        uploader.Admin.mbd_prepare(self.request, uploader)
        uploader.Admin.mbd_check(self.request, uploader)
        self.msglog.info("Uploader profile changed: {u}".format(u=uploader))
        self.msglog.warn("Your uploader profile must be (re-)activated by the mini-buildd staff before you can actually use it.")


class Subscription(Command):
    """Manage subscriptions to package notifications.

    A package subscription is a tuple 'PACKAGE:DISTRIBUTION',
    where both PACKAGE or DISTRIBUTION may be empty to denote
    all resp. items.
    """
    COMMAND = "subscription"
    AUTH = Command.LOGIN
    ARGUMENTS = [
        (["action"], {"choices": ["list", "add", "remove"], "help": "action to run"}),
        (["subscription"], {"help": "subscription pattern"})]

    def run(self, daemon):
        package, _sep, distribution = self.args["subscription"].partition(":")

        def _filter():
            for s in daemon.get_subscription_objects().filter(subscriber=self.request.user):
                if (package == "" or s.package == package) and (distribution == "" or s.distribution == distribution):
                    yield s

        def _delete(subscription):
            result = "{s}".format(s=subscription)
            subscription.delete()
            return result

        if self.args["action"] == "list":
            self._plain_result = "\n".join(["{s}.".format(s=subscription) for subscription in _filter()])

        elif self.args["action"] == "add":
            subscription, created = daemon.get_subscription_objects().get_or_create(subscriber=self.request.user,
                                                                                    package=package,
                                                                                    distribution=distribution)
            self._plain_result = "{a}: {s}.".format(a="Added" if created else "Exists", s=subscription)

        elif self.args["action"] == "remove":
            self._plain_result = "\n".join(["Removed: {s}.".format(s=_delete(subscription)) for subscription in _filter()])

        else:
            raise Exception("Unknown action '{c}': Use one of 'list', 'add' or 'remove'.".format(c=self.args["action"]))

        # For convenience, say something if nothing matched
        if not self._plain_result:
            self._plain_result = "No matching subscriptions ({s}).".format(s=self.args["subscription"])

COMMAND_GROUP = "__GROUP__"
COMMANDS = [(COMMAND_GROUP, "Daemon commands"),
            (Status.COMMAND, Status),
            (Start.COMMAND, Start),
            (Stop.COMMAND, Stop),
            (PrintUploaders.COMMAND, PrintUploaders),
            (Meta.COMMAND, Meta),
            (COMMAND_GROUP, "Configuration convenience commands"),
            (GetKey.COMMAND, GetKey),
            (GetDputConf.COMMAND, GetDputConf),
            (GetSourcesList.COMMAND, GetSourcesList),
            (LogCat.COMMAND, LogCat),
            (COMMAND_GROUP, "Package management commands"),
            (List.COMMAND, List),
            (Show.COMMAND, Show),
            (Migrate.COMMAND, Migrate),
            (Remove.COMMAND, Remove),
            (Port.COMMAND, Port),
            (PortExt.COMMAND, PortExt),
            (Retry.COMMAND, Retry),
            (COMMAND_GROUP, "User management commands"),
            (SetUserKey.COMMAND, SetUserKey),
            (Subscription.COMMAND, Subscription),
            ]

COMMANDS_DICT = dict(COMMANDS)

COMMANDS_DEFAULTS = [(cmd, cls(cls.get_default_args()) if cmd != COMMAND_GROUP else cls) for cmd, cls in COMMANDS]

if __name__ == "__main__":
    mini_buildd.misc.setup_console_logging()
    import doctest
    doctest.testmod()
