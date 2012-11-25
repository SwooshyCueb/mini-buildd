# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import pickle
import logging

import mini_buildd.misc

LOG = logging.getLogger(__name__)


class Command(object):
    COMMAND = None
    LOGIN = False
    CONFIRM = False
    ARGUMENTS = []

    @classmethod
    def _filter_api_args(cls, args):
        result = {}
        for sargs, kvsargs in cls.ARGUMENTS:
            # Sanitize args
            # '--with-xyz' -> 'with_xyz'
            arg = sargs[0].replace("--", "", 1).replace("-", "_")
            if arg in args:
                result[arg] = args[arg]
            elif "default" in kvsargs:
                result[arg] = kvsargs["default"]

            # Check required
            if sargs[0][:2] != "--" or ("required" in kvsargs and kvsargs["required"]):
                if not arg in args or not args[arg]:
                    raise Exception("Missing required argument {a}".format(a=arg))

        return result

    def __init__(self, args):
        self.args = self._filter_api_args(args)

    def has_flag(self, flag):
        return self.args.get(flag, "False") == "True"


class Status(Command):
    """
    Show the status of the mini-buildd instance.
    """
    COMMAND = "status"

    def __init__(self, args):
        super(Status, self).__init__(args)

        self.version = "-1"
        self.http = ""
        self.ftp = ""
        self.running = False
        self.load = 0.0
        self.chroots = {}
        self.repositories = {}
        self.remotes = {}

    def run(self, daemon):
        # version string
        self.version = mini_buildd.__version__

        # hopo string
        self.http = daemon.model.mbd_get_http_hopo().string

        # hopo string
        self.ftp = daemon.model.mbd_get_ftp_hopo().string

        # bool
        self.running = daemon.is_running()

        # float value: 0 =< load <= 1
        self.load = daemon.build_queue.load

        # chroots: {"i386": ["sid", "wheezy"], "amd64": ["wheezy"]}
        for c in daemon.get_active_chroots():
            self.chroots.setdefault(c.architecture.name, [])
            self.chroots[c.architecture.name].append(c.source.codename)

        # repositories: {"repo1": ["sid", "wheezy"], "repo2": ["squeeze"]}
        for r in daemon.get_active_repositories():
            self.repositories[r.identity] = [d.base_source.codename for d in r.distributions.all()]

        # remotes: ["host1.xyz.org:8066", "host2.xyz.org:8066"]
        self.remotes = [r.http for r in daemon.get_active_remotes()]

    def __unicode__(self):
        return """\
Mini-buildd : {hs}: http://{h} ({v})
Daemon      : {ds}: ftp://{f} (load {l})

Repositories: {r}
Chroots     : {c}
Remotes     : {rm}
""".format(h=self.http,
           v=self.version,
           hs="UP" if self.running else "UP  ",
           ds="UP" if self.running else "DOWN",
           f=self.ftp,
           l=self.load,
           r=", ".join(["{i}: {c}".format(i=identity, c=" ".join(codenames)) for identity, codenames in self.repositories.items()]),
           c=", ".join(["{a}: {c}".format(a=arch, c=" ".join(codenames)) for arch, codenames in self.chroots.items()]),
           rm=", ".join(self.remotes))

    def has_chroot(self, arch, codename):
        return arch in self.chroots and codename in self.chroots[arch]


class GetKey(Command):
    """
    Get GnuPG public key.
    """
    COMMAND = "getkey"

    def __init__(self, args):
        super(GetKey, self).__init__(args)
        self.key = ""

    def run(self, daemon):
        self.key = daemon.model.mbd_get_pub_key()

    def __unicode__(self):
        return self.key


class GetDputConf(Command):
    """
    Get recommended dput config snippet.

    Usually, this is for integration in your personal ~/.dput.cf.
    """
    COMMAND = "getdputconf"

    def __init__(self, args):
        super(GetDputConf, self).__init__(args)
        self.conf = ""

    def run(self, daemon):
        self.conf = daemon.model.mbd_get_dput_conf()

    def __unicode__(self):
        return self.conf


class LogCat(Command):
    """
    Cat last n lines of the mini-buildd's log.
    """
    COMMAND = "logcat"
    ARGUMENTS = [
        (["--lines", "-n"], {"action": "store", "metavar": "N", "type": int,
                             "default": 50,
                             "help": "Cat (approx.) the last N lines."})]

    def __init__(self, args):
        super(LogCat, self).__init__(args)
        self.log = ""

    def run(self, daemon):
        self.log = daemon.logcat(lines=int(self.args["lines"]))

    def __unicode__(self):
        return self.log


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
    """
    List packages matching a shell-like glob pattern; matches both source and binary package names.
    """
    COMMAND = "list"
    ARGUMENTS = [
        (["pattern"], {"help": "List source packages matching pattern"}),
        (["--with-rollbacks", "-r"], {"action": "store_true",
                                      "default": False,
                                      "help": "Also list packages on rollback distributions"}),
        (["--type", "-T"], {"action": "store", "metavar": "TYPE",
                            "default": "",
                            "help": "Package type: dsc, deb or udeb (like reprepo --type)."})]

    def __init__(self, args):
        super(List, self).__init__(args)
        self.repositories = {}

    def run(self, daemon):
        # Save all results of all repos in a top-level dict (don't add repos with empty results).
        for r in daemon.get_active_repositories():
            r_result = r.mbd_package_list(self.args["pattern"],
                                          typ=self.args["type"] if self.args["type"] else None,
                                          with_rollbacks=self.has_flag("with_rollbacks"))
            if r_result:
                self.repositories[r.identity] = r_result

    def __unicode__(self):
        if not self.repositories:
            return "No packages found."

        fmt, hdr, fmt_tle, sep0, sep1 = _get_table_format(self.repositories,
                                                          [("package", "Package"),
                                                           ("type", "Type"),
                                                           ("architecture", "Arch"),
                                                           ("distribution", "Distribution"),
                                                           ("version", "Version"),
                                                           ("source", "Source")])

        def p_table(repository, values):
            return """\
{s0}
{t}
{s0}
{h}
{s1}
{p}""".format(t=fmt_tle.format(t=" Repository '{r}' ".format(r=repository)),
              h=hdr,
              s0=sep0,
              s1=sep1,
              p="\n".join([fmt.format(**p) for p in values]))

        return "\n".join([p_table(k, v) for k, v in self.repositories.items()])


class Show(Command):
    """
    Show a source package.
    """
    COMMAND = "show"
    ARGUMENTS = [
        (["package"], {"help": "Source package name"}),
        (["--verbose", "-v"], {"action": "store_true",
                               "default": False,
                               "help": "Verbose output"})]

    def __init__(self, args):
        super(Show, self).__init__(args)
        self.repositories = {}

    def run(self, daemon):
        # Save all results of all repos in a top-level dict (don't add repos with empty results).
        for r in daemon.get_active_repositories():
            r_result = r.mbd_package_show(self.args["package"])
            if r_result:
                self.repositories[r.identity] = r_result

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
            rows.append(("dsc", "Source URL"))
            rows.append(("rollbacks_str_verbose", "Rollbacks"))
        else:
            rows.append(("rollbacks_str", "Rollbacks"))

        result = ""
        for repository, codenames in self.repositories.items():
            # Add rollback_str
            for k, v in codenames:
                for d in v:
                    d["rollbacks_str"] = "{n}/{m}".format(n=len(d["rollbacks"]), m=d["rollback"])
                    d["rollbacks_str_verbose"] = d["rollbacks_str"] + \
                        ": " + " ".join(["{n}:{v}".format(n=r["no"], v=r["sourceversion"]) for r in d["rollbacks"]])

            fmt, hdr, fmt_tle, sep0, sep1 = _get_table_format(codenames, rows)
            result += "{s}\n{t}\n".format(s=sep0, t=fmt_tle.format(t="Repository '{r}'".format(r=repository)))
            result += "\n".join([p_codename(k, v) for k, v in codenames])
        return result


class Migrate(Command):
    """
    Migrate a source package (along with all binary packages).
    """
    COMMAND = "migrate"
    LOGIN = True
    CONFIRM = True
    ARGUMENTS = [
        (["package"], {"help": "Source package name."}),
        (["distribution"], {"help": "Distribution to migrate from (if this is a '-rollbackN' distribution, this will perform a rollback restore.)"})]

    def __init__(self, args):
        super(Migrate, self).__init__(args)
        self.cmd_out = ""

    def run(self, daemon):
        repository, distribution, suite, rollback = daemon.parse_distribution(self.args["distribution"])
        self.cmd_out = repository.mbd_package_migrate(self.args["package"], distribution, suite, rollback)

    def __unicode__(self):
        return self.cmd_out


class Remove(Command):
    """
    Remove a source package (along with all binary packages).
    """
    COMMAND = "remove"
    LOGIN = True
    CONFIRM = True
    ARGUMENTS = [
        (["package"], {"help": "Source package name."}),
        (["distribution"], {"help": "Distribution to remove from."})]

    def __init__(self, args):
        super(Remove, self).__init__(args)
        self.cmd_out = ""

    def run(self, daemon):
        repository, distribution, suite, rollback = daemon.parse_distribution(self.args["distribution"])
        self.cmd_out = repository.mbd_package_remove(self.args["package"], distribution, suite, rollback)

    def __unicode__(self):
        return self.cmd_out


class Port(Command):
    """
    Port any source package to (a) mini-buildd distribution(s).

    A 'port' is a unchanged rebuild of the given source package.
    """
    COMMAND = "port"
    LOGIN = True
    CONFIRM = True
    ARGUMENTS = [
        (["dsc"], {"help": "Debian source package (dsc) URL."}),
        (["distributions"], {"help": "Comma-separated list of distributions to port to."})]

    def __init__(self, args):
        super(Port, self).__init__(args)

        # Parse and pre-check all dists
        self.results = ""

    def run(self, daemon):
        # Parse and pre-check all dists
        for d in self.args["distributions"].split(","):
            try:
                daemon.port(self.args["dsc"], d, None)
                self.results += "{dsc}->{d}: Portrequest uploaded.\n".format(dsc=self.args["dsc"], d=d)
            except Exception as e:
                self.results += "{dsc}->{d}: Portrequest FAILed: {e}.\n".format(dsc=self.args["dsc"], d=d, e=e)

    def __unicode__(self):
        return self.results


COMMANDS = {Status.COMMAND: Status,
            GetKey.COMMAND: GetKey,
            GetDputConf.COMMAND: GetDputConf,
            LogCat.COMMAND: LogCat,
            List.COMMAND: List,
            Show.COMMAND: Show,
            Migrate.COMMAND: Migrate,
            Remove.COMMAND: Remove,
            Port.COMMAND: Port,
            }


if __name__ == "__main__":
    mini_buildd.misc.setup_console_logging()

    T0 = Status(True, "xyz:123", 0.5, {}, {})
    pickle.dump(T0, open("./pickle.test", "w"))

    T1 = pickle.load(open("./pickle.test"))
    print("{}".format(T1))
    print(T1.__class__.__name__)
    print(T1.has_chroot("i386", "squeeze"))

    import doctest
    doctest.testmod()
