# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import re
import time
import shutil
import glob
import tempfile
import threading
import subprocess
import Queue
import collections
import urllib2
import logging

import debian.deb822
import debian.changelog
import debian.debian_support

import mini_buildd.misc
import mini_buildd.changes
import mini_buildd.gnupg
import mini_buildd.api
import mini_buildd.ftpd
import mini_buildd.packager
import mini_buildd.builder

import mini_buildd.models.daemon
import mini_buildd.models.repository
import mini_buildd.models.chroot
import mini_buildd.models.gnupg
import mini_buildd.models.subscription

LOG = logging.getLogger(__name__)


class Changelog(debian.changelog.Changelog):
    """
    Changelog class with some extra functions.

    >>> cl = Changelog(mini_buildd.misc.open_utf8("./examples/doctests/changelog"), max_blocks=100)
    >>> cl.find_first_not("mini-buildd@buildd.intra")
    (u'Stephan S\\xfcrken <absurd@debian.org>', u'1.0.0-2')

    >>> cl = Changelog(mini_buildd.misc.open_utf8("./examples/doctests/changelog.ported"), max_blocks=100)
    >>> cl.find_first_not("mini-buildd@buildd.intra")
    (u'Stephan S\\xfcrken <absurd@debian.org>', u'1.0.0-2')

    >>> cl = Changelog(mini_buildd.misc.open_utf8("./examples/doctests/changelog.oneblock"), max_blocks=100)
    >>> cl.find_first_not("mini-buildd@buildd.intra")
    (u'Stephan S\\xfcrken <absurd@debian.org>', u'1.0.1-1~')

    >>> cl = Changelog(mini_buildd.misc.open_utf8("./examples/doctests/changelog.oneblock.ported"), max_blocks=100)
    >>> cl.find_first_not("mini-buildd@buildd.intra")
    (u'Mini Buildd <mini-buildd@buildd.intra>', u'1.0.1-1~')
    """
    def find_first_not(self, author):
        "Find (author,version+1) of the first changelog block not by given author."
        def s2u(string):
            "Compat for python-debian <= 0.1.19: Author strings are of class 'str', not 'unicode'."
            return unicode(string) if isinstance(string, str) else string

        result = (None, None)
        for index, block in enumerate(self._blocks):
            result = (s2u(block.author),
                      "{v}".format(v=self._blocks[index + 1].version) if len(self._blocks) > (index + 1) else "{v}~".format(v=block.version))
            if author not in s2u(block.author):
                break
        return result


class DebianVersion(debian.debian_support.Version):
    @classmethod
    def _sub_rightmost(cls, pattern, repl, string):
        last_match = None
        for last_match in re.finditer(pattern, string):
            pass
        if last_match:
            return string[:last_match.start()] + repl + string[last_match.end():]
        else:
            return string + repl

    @classmethod
    def _get_rightmost(cls, pattern, string):
        last_match = None
        for last_match in re.finditer(pattern, string):
            pass
        if last_match:
            return string[last_match.start():last_match.end()]
        else:
            return ""

    @classmethod
    def stamp(cls):
        # 20121218151309
        return time.strftime("%Y%m%d%H%M%S", time.gmtime())

    @classmethod
    def stamp_regex(cls, stamp=None):
        return r"[0-9]{{{n}}}".format(n=len(stamp if stamp else cls.stamp()))

    def gen_internal_rebuild(self):
        r"""
        Generate an 'internal rebuild' version.

        If the version is not already a rebuild version, just
        append the rebuild appendix, otherwise replace the old
        one. For example::

          1.2.3 -> 1.2.3+rebuilt20130215100453
          1.2.3+rebuilt20130215100453 -> 1.2.3+rebuilt20130217120517

        Code samples:

        >>> regex = r"^1\.2\.3\+rebuilt{s}$".format(s=DebianVersion.stamp_regex())
        >>> bool(re.match(regex, DebianVersion("1.2.3").gen_internal_rebuild()))
        True
        >>> bool(re.match(regex, DebianVersion("1.2.3+rebuilt20130215100453").gen_internal_rebuild()))
        True
        """
        stamp = self.stamp()
        return self._sub_rightmost(r"\+rebuilt" + self.stamp_regex(stamp),
                                   "+rebuilt" + stamp,
                                   self.full_version)

    def gen_external_port(self, default_version):
        """
        Generate an 'external port' version.

        This currently just appends the given default version
        appendix. For example:

        1.2.3 -> 1.2.3~test60+1
        """
        return "{v}{d}".format(v=self.full_version, d=default_version)

    def gen_internal_port(self, from_mandatory_version_regex, to_default_version):
        r"""
        Generate an 'internal port' version.

        Tests for the (recommended) Default layout:

        >>> sid_regex = r"~testSID\+[1-9]"
        >>> sid_default = "~testSID+1"
        >>> sid_exp_regex = r"~testSID\+0"
        >>> sid_exp_default = "~testSID+0"
        >>> wheezy_regex = r"~test70\+[1-9]"
        >>> wheezy_default = "~test70+1"
        >>> wheezy_exp_regex = r"~test70\+0"
        >>> wheezy_exp_default = "~test70+0"
        >>> squeeze_regex = r"~test60\+[1-9]"
        >>> squeeze_default = "~test60+1"
        >>> squeeze_exp_regex = r"~test60\+0"
        >>> squeeze_exp_default = "~test60+0"

        sid->wheezy ports:

        >>> DebianVersion("1.2.3-1~testSID+1").gen_internal_port(sid_regex, wheezy_default)
        u'1.2.3-1~test70+1'
        >>> DebianVersion("1.2.3-1~testSID+4").gen_internal_port(sid_regex, wheezy_default)
        u'1.2.3-1~test70+4'
        >>> DebianVersion("1.2.3-1~testSID+4fud15").gen_internal_port(sid_regex, wheezy_default)
        u'1.2.3-1~test70+4fud15'
        >>> DebianVersion("1.2.3-1~testSID+0").gen_internal_port(sid_exp_regex, wheezy_exp_default)
        u'1.2.3-1~test70+0'
        >>> DebianVersion("1.2.3-1~testSID+0exp2").gen_internal_port(sid_exp_regex, wheezy_exp_default)
        u'1.2.3-1~test70+0exp2'

        wheezy->squeeze ports:

        >>> DebianVersion("1.2.3-1~test70+1").gen_internal_port(wheezy_regex, squeeze_default)
        u'1.2.3-1~test60+1'
        >>> DebianVersion("1.2.3-1~test70+4").gen_internal_port(wheezy_regex, squeeze_default)
        u'1.2.3-1~test60+4'
        >>> DebianVersion("1.2.3-1~test70+4fud15").gen_internal_port(wheezy_regex, squeeze_default)
        u'1.2.3-1~test60+4fud15'
        >>> DebianVersion("1.2.3-1~test70+0").gen_internal_port(wheezy_exp_regex, squeeze_exp_default)
        u'1.2.3-1~test60+0'
        >>> DebianVersion("1.2.3-1~test70+0exp2").gen_internal_port(wheezy_exp_regex, squeeze_exp_default)
        u'1.2.3-1~test60+0exp2'

        No version restrictions: just add default version

        >>> DebianVersion("1.2.3-1").gen_internal_port(".*", "~port+1")
        u'1.2.3-1~port+1'
        """
        from_apdx = self._get_rightmost(from_mandatory_version_regex, self.full_version)
        from_apdx_plus_revision = self._get_rightmost(r"\+[0-9]", from_apdx)
        if from_apdx and from_apdx_plus_revision:
            actual_to_default_version = self._sub_rightmost(r"\+[0-9]", from_apdx_plus_revision, to_default_version)
        else:
            actual_to_default_version = to_default_version
        return self._sub_rightmost(from_mandatory_version_regex, actual_to_default_version, self.full_version)


class KeyringPackage(mini_buildd.misc.TmpDir):
    def __init__(self, identity, gpg, debfullname, debemail, tpl_dir="/usr/share/doc/mini-buildd/examples/packages/archive-keyring-template"):
        super(KeyringPackage, self).__init__()

        self.key_id = gpg.get_first_sec_key().key_id
        LOG.debug("KeyringPackage using key: '{i}'".format(i=self.key_id))

        self.package_name = "{i}-archive-keyring".format(i=identity)
        self.environment = mini_buildd.misc.taint_env(
            {"DEBEMAIL": debemail,
             "DEBFULLNAME": debfullname,
             "GNUPGHOME": gpg.home})
        self.version = DebianVersion.stamp()

        # Copy template, and replace %ID%, %MAINT% and %KEY_ID% in all files
        p = os.path.join(self.tmpdir, "package")
        shutil.copytree(tpl_dir, p)
        for root, _dirs, files in os.walk(p):
            for f in files:
                old_file = os.path.join(root, f)
                new_file = old_file + ".new"
                mini_buildd.misc.open_utf8(new_file, "w").write(
                    mini_buildd.misc.subst_placeholders(
                        mini_buildd.misc.open_utf8(old_file, "r").read(),
                        {"ID": identity,
                         "KEY_ID": self.key_id,
                         "MAINT": "{n} <{e}>".format(n=debfullname, e=debemail)}))
                os.rename(new_file, old_file)

        # Export public GnuPG key into the package
        gpg.export(os.path.join(p, self.package_name + ".gpg"), identity=self.key_id)

        # Generate sources.lists
        daemon = get()
        for r in mini_buildd.models.repository.Repository.objects.all():
            for d in r.distributions.all():
                for s in r.layout.suiteoption_set.all():
                    for rb in [None] + range(s.rollback):
                        file_base = "{codename}_{archive}_{repository}_{suite}{rollback}".format(codename=d.base_source.codename,
                                                                                                 archive=daemon.model.identity,
                                                                                                 repository=r.identity,
                                                                                                 suite=s.suite.name,
                                                                                                 rollback="" if rb is None else "-rollback{rb}".format(rb=rb))
                        for prefix, appendix in [("deb ", ""), ("deb-src ", "_src")]:
                            apt_line = d.mbd_get_apt_line(r, s, rollback=rb, prefix=prefix)
                            file_name = "{base}{appendix}.list".format(base=file_base, appendix=appendix)
                            mini_buildd.misc.open_utf8(os.path.join(p, file_name), "w").write(apt_line + "\n")

        # Generate changelog entry
        mini_buildd.misc.call(["debchange",
                               "--create",
                               "--package={p}".format(p=self.package_name),
                               "--newversion={v}".format(v=self.version),
                               "Automatic keyring package for archive '{i}'.".format(i=identity)],
                              cwd=p,
                              env=self.environment)

        mini_buildd.misc.call(["dpkg-source",
                               "-b",
                               "package"],
                              cwd=self.tmpdir,
                              env=self.environment)

        # Compute DSC file name
        self.dsc = os.path.join(self.tmpdir,
                                mini_buildd.changes.Changes.gen_dsc_file_name(self.package_name,
                                                                              self.version))


class DSTPackage(mini_buildd.misc.TmpDir):
    def __init__(self, tpl_dir, version=None):
        super(DSTPackage, self).__init__()

        dst_dir = os.path.join(self.tmpdir, "package")
        shutil.copytree(tpl_dir, dst_dir)
        if version:
            mini_buildd.misc.call(["debchange",
                                   "--newversion={v}".format(v=version),
                                   "Version update '{v}'.".format(v=version)],
                                  cwd=dst_dir)
        mini_buildd.misc.call(["dpkg-source", "-b", "package"], cwd=self.tmpdir)
        self.dsc = glob.glob(os.path.join(self.tmpdir, "*.dsc"))[0]


class Keyrings(object):
    """
    Hold/manage all gnupg keyrings (for remotes and all repository uploaders).
    """
    def __init__(self):
        self._our_pub_key = get().model.mbd_get_pub_key()
        self._remotes = self._gen_remotes()
        self._uploaders = self._gen_uploaders()
        self._needs_update = False

    def set_needs_update(self):
        self._needs_update = True

    def close(self):
        self._remotes.close()
        for u in self._uploaders.values():
            u.close()

    def _update(self):
        if self._needs_update:
            self.close()
            self.__init__()

    def get_remotes(self):
        self._update()
        return self._remotes

    def get_uploaders(self):
        self._update()
        return self._uploaders

    def _gen_remotes(self):
        remotes = mini_buildd.gnupg.TmpGnuPG()
        # keyring["remotes"]: Remotes keyring to authorize buildrequests and buildresults
        # Always add our own key
        if self._our_pub_key:
            remotes.add_pub_key(self._our_pub_key)
        for r in mini_buildd.models.gnupg.Remote.mbd_get_active_or_auto_reactivate():
            remotes.add_pub_key(r.key)
            LOG.info("Remote key added for '{r}': {k}: {n}".format(r=r, k=r.key_long_id, n=r.key_name))
        return remotes

    def _gen_uploaders(self):
        "All uploader keyrings for each repository."
        uploaders = {}
        for r in mini_buildd.models.repository.Repository.mbd_get_active():
            uploaders[r.identity] = r.mbd_get_uploader_keyring()
            # Always add our key too for internal builds
            if self._our_pub_key:
                uploaders[r.identity].add_pub_key(self._our_pub_key)
        return uploaders


def run():
    """
    mini-buildd 'daemon engine' run.
    """

    ftpd_thread = mini_buildd.misc.run_as_thread(
        mini_buildd.ftpd.run,
        bind=get().model.ftpd_bind,
        queue=get().incoming_queue)

    builder_thread = mini_buildd.misc.run_as_thread(
        mini_buildd.builder.run,
        daemon_=get())

    while True:
        event = get().incoming_queue.get()
        if event == "SHUTDOWN":
            break

        try:
            LOG.info("Status: {0} active packages, {0} changes waiting in incoming.".
                     format(len(get().packages), get().incoming_queue.qsize()))

            changes = None
            changes = mini_buildd.changes.Changes(event)

            if changes.type == changes.TYPE_BREQ:
                # Build request: builder

                def queue_buildrequest(event):
                    "Queue in extra thread so we don't block here in case builder is busy."
                    get().build_queue.put(event)
                mini_buildd.misc.run_as_thread(queue_buildrequest, daemon=True, event=event)

            else:
                # User upload or build result: packager
                mini_buildd.packager.run(
                    daemon=get(),
                    changes=changes)

        except Exception as e:
            mini_buildd.setup.log_exception(LOG, "Invalid changes file", e)

            # Try to notify
            try:
                subject = "INVALID CHANGES: {c}: {e}".format(c=event, e=e)
                body = mini_buildd.misc.open_utf8(event, "r").read()
                get().model.mbd_notify(subject, body)
            except Exception as e:
                mini_buildd.setup.log_exception(LOG, "Invalid changes notify failed", e)

            # Try to clean up
            try:
                if changes:
                    changes.remove()
                else:
                    os.remove(event)
            except Exception as e:
                mini_buildd.setup.log_exception(LOG, "Invalid changes cleanup failed", e)

        finally:
            get().incoming_queue.task_done()

    get().build_queue.put("SHUTDOWN")
    mini_buildd.ftpd.shutdown()
    builder_thread.join()
    ftpd_thread.join()

    # keyrings.close() is not called implicitly; this leaves tmp files around.
    # There should be a nicer way, really...
    try:
        get().keyrings.close()
    except:
        pass


class Daemon(object):
    def __init__(self):
        # Set global to ourself
        global _INSTANCE
        _INSTANCE = self

        # When this is not None, daemon is running
        self.thread = None
        # Protects start/stop from parallel calls
        self.lock = threading.Lock()

        # Vars that are (re)generated when the daemon model is updated
        self.model = None
        self.keyrings = None
        self.incoming_queue = None
        self.build_queue = None
        self.packages = None
        self.builds = None
        self.last_packages = None
        self.last_builds = None

    def __unicode__(self):
        return "{r}: {d}".format(r="UP" if self.is_running() else "DOWN", d=self.model)

    @classmethod
    def _new_model_object(cls):
        model, created = mini_buildd.models.daemon.Daemon.objects.get_or_create(id=1)
        if created:
            LOG.info("New default Daemon model instance created")
        return model

    def _update_from_model(self):
        self.model = self._new_model_object()

        if self.keyrings is None:
            self.keyrings = Keyrings()
        else:
            self.keyrings.set_needs_update()
        self.incoming_queue = Queue.Queue()
        self.build_queue = mini_buildd.misc.BlockQueue(maxsize=self.model.build_queue_size)
        self.packages = {}
        self.builds = {}
        self.last_packages = collections.deque(maxlen=self.model.show_last_packages)
        self.last_builds = collections.deque(maxlen=self.model.show_last_builds)

        # Try to unpickle last_* from persistent storage.
        # Objects must match API, and we don't care if it fails.
        try:
            last_packages, last_builds = self.model.mbd_get_pickled_data()
            for p in last_packages:
                if p.api_check():
                    self.last_packages.append(p)
                else:
                    LOG.warn("Removing (new API) from last package info: {p}".format(p=p))
            for b in last_builds:
                if b.api_check():
                    self.last_builds.append(b)
                else:
                    LOG.warn("Removing (new API) from last builds info: {b}".format(b=b))
        except Exception as e:
            mini_buildd.setup.log_exception(LOG, "Error adding persisted last builds/packages (ignoring)", e, logging.WARN)

    def update_to_model(self, obj):
        obj.mbd_set_pickled_data((self.last_packages, self.last_builds))

    def start(self, force_check=False, msglog=LOG):
        with self.lock:
            if not self.thread:
                self._update_from_model()
                msglog.info("Checking daemon (force={f}).".format(f=force_check))
                mini_buildd.models.daemon.Daemon.Admin.mbd_action(None, (self.model,), "check", force=force_check)
                if self.model.mbd_is_active():
                    self.thread = mini_buildd.misc.run_as_thread(run)
                    msglog.info("Daemon started.")
                else:
                    msglog.warn("Daemon is deactivated (won't start). Please (re)configure your instance as superuser.")
            else:
                msglog.info("Daemon already running.")

        return self.is_running()

    def stop(self, msglog=LOG):
        with self.lock:
            if self.thread:
                # Save pickled persistend state; as a workaround, save the whole model but on fresh object/db state.
                # With django 1.5, we could just use save(update_fields=["pickled_data"]) on self.model
                model = self._new_model_object()
                self.update_to_model(model)
                model.save()

                self.incoming_queue.put("SHUTDOWN")
                self.thread.join()
                self.thread = None
                self._update_from_model()
                msglog.info("Daemon stopped.")
            else:
                msglog.info("Daemon already stopped.")

        return not self.is_running()

    def is_busy(self):
        return self.lock.locked()

    def is_running(self):
        return not self.is_busy() and bool(self.thread)

    def get_status(self):
        status = mini_buildd.api.Status([])
        status.run(self)
        return status

    @classmethod
    def meta(cls, model, func, msglog):
        # pylint: disable=W0123
        model_class = eval("mini_buildd.models.{m}.Admin".format(m=model))
        getattr(model_class, "mbd_meta_{f}".format(f=func))(msglog)

    @classmethod
    def logcat(cls, lines):
        logfile = mini_buildd.misc.open_utf8(mini_buildd.setup.LOG_FILE, "r")
        return mini_buildd.misc.tail(logfile, lines)

    @classmethod
    def get_active_chroots(cls):
        return mini_buildd.models.chroot.Chroot.mbd_get_active()

    @classmethod
    def get_active_repositories(cls):
        return mini_buildd.models.repository.Repository.mbd_get_active()

    @classmethod
    def get_active_remotes(cls):
        return mini_buildd.models.gnupg.Remote.mbd_get_active()

    @classmethod
    def get_active_or_auto_reactivate_remotes(cls):
        return mini_buildd.models.gnupg.Remote.mbd_get_active_or_auto_reactivate()

    @classmethod
    def get_subscription_objects(cls):
        return mini_buildd.models.subscription.Subscription.objects

    @classmethod
    def parse_distribution(cls, dist):
        """
        Get repository, distribution and suite model objects (plus rollback no) from distribtion string.
        """
        # Check and parse changes distribution string
        dist_parsed = mini_buildd.misc.Distribution(dist, mini_buildd.models.repository.get_meta_distribution_map())

        # Get repository for identity; django exceptions will suite quite well as-is
        repository = mini_buildd.models.repository.Repository.objects.get(identity=dist_parsed.repository)
        distribution = repository.distributions.all().get(base_source__codename__exact=dist_parsed.codename)
        suite = repository.layout.suiteoption_set.all().get(suite__name=dist_parsed.suite)

        return repository, distribution, suite, dist_parsed.rollback_no

    def port(self, package, from_dist, to_dist, version):
        # check from_dist
        from_repository, from_distribution, from_suite, _from_rollback = self.parse_distribution(from_dist)
        p = from_repository.mbd_package_find(package, distribution=from_dist, version=version)
        if not p:
            raise Exception("Port failed: Package (version) for '{p}' not found in '{d}'".format(p=package, d=from_dist))

        # check to_dist
        to_repository, to_distribution, to_suite, to_rollback = self.parse_distribution(to_dist)
        if not to_suite.uploadable:
            raise Exception("Port failed: Non-upload distribution requested: '{d}'".format(d=to_dist))
        if to_rollback:
            raise Exception("Port failed: Rollback distribution requested: '{d}'".format(d=to_dist))

        # Ponder version to use
        v = DebianVersion(p["sourceversion"])
        if to_dist == from_dist:
            port_version = v.gen_internal_rebuild()
        else:
            port_version = v.gen_internal_port(from_repository.layout.mbd_get_mandatory_version_regex(from_repository, from_distribution, from_suite),
                                               to_repository.layout.mbd_get_default_version(to_repository, to_distribution, to_suite))

        _component, url = from_repository.mbd_get_dsc_url(from_distribution, package, p["sourceversion"])
        if not url:
            raise Exception("Port failed: Can't find DSC for {p}-{v} in pool".format(p=package, v=p["sourceversion"]))

        self._port(url, package, to_dist, port_version)

    def portext(self, dsc_url, to_dist):
        # check to_dist
        to_repository, to_distribution, to_suite, to_rollback = self.parse_distribution(to_dist)

        if not to_suite.uploadable:
            raise Exception("Port failed: Non-upload distribution requested: '{d}'".format(d=to_dist))

        if to_rollback:
            raise Exception("Port failed: Rollback distribution requested: '{d}'".format(d=to_dist))

        dsc = debian.deb822.Dsc(urllib2.urlopen(dsc_url))
        v = DebianVersion(dsc["Version"])
        self._port(dsc_url,
                   dsc["Source"],
                   to_dist,
                   v.gen_external_port(to_repository.layout.mbd_get_default_version(to_repository, to_distribution, to_suite)),
                   extra_cl_entries=["External port from: {u}".format(u=dsc_url)])

    def _port(self, dsc_url, package, dist, version, extra_cl_entries=None):
        t = mini_buildd.misc.TmpDir()
        try:
            env = mini_buildd.misc.taint_env({"DEBEMAIL": self.model.email_address,
                                              "DEBFULLNAME": self.model.mbd_fullname,
                                              "GNUPGHOME": self.model.mbd_gnupg.home})

            # Download DSC via dget.
            mini_buildd.misc.call(["dget",
                                   "--allow-unauthenticated",
                                   "--download-only",
                                   dsc_url],
                                  cwd=t.tmpdir,
                                  env=env)

            # Get SHA1 of original dsc file
            original_dsc_sha1sum = mini_buildd.misc.sha1_of_file(os.path.join(t.tmpdir, os.path.basename(dsc_url)))

            # Unpack DSC (note: dget does not support -x to a dedcicated dir).
            dst = "debian_source_tree"
            mini_buildd.misc.call(["dpkg-source",
                                   "-x",
                                   os.path.basename(dsc_url),
                                   dst],
                                  cwd=t.tmpdir,
                                  env=env)

            dst_path = os.path.join(t.tmpdir, dst)

            # Get version and author from original changelog; use the first block not
            original_author, original_version = Changelog(mini_buildd.misc.open_utf8(os.path.join(dst_path, "debian", "changelog"), "r"),
                                                          max_blocks=100).find_first_not(self.model.email_address)
            LOG.debug("Port: Found original version/author: {v}/{a}".format(v=original_version, a=original_author))

            # Change changelog in DST
            mini_buildd.misc.call(["debchange",
                                   "--newversion={v}".format(v=version),
                                   "--force-distribution",
                                   "--force-bad-version",
                                   "--preserve",
                                   "--dist={d}".format(d=dist),
                                   "Automated port via mini-buildd (no changes). Original DSC's SHA1: {s}.".format(s=original_dsc_sha1sum)],
                                  cwd=dst_path,
                                  env=env)

            for entry in (extra_cl_entries or []) + ["MINI_BUILDD: BACKPORT_MODE"]:
                mini_buildd.misc.call(["debchange",
                                       "--append",
                                       entry],
                                      cwd=dst_path,
                                      env=env)

            # Repack DST
            mini_buildd.misc.call(["dpkg-source", "-b", dst], cwd=t.tmpdir, env=env)
            dsc = os.path.join(t.tmpdir,
                               mini_buildd.changes.Changes.gen_dsc_file_name(package,
                                                                             version))
            self.model.mbd_gnupg.sign(dsc)

            # Gen changes file name
            changes = os.path.join(t.tmpdir,
                                   mini_buildd.changes.Changes.gen_changes_file_name(package,
                                                                                     version,
                                                                                     "source"))

            # Generate Changes file
            with tempfile.TemporaryFile() as err:
                with mini_buildd.misc.open_utf8(changes, "w") as out:
                    subprocess.check_call(["dpkg-genchanges",
                                           "-S",
                                           "-sa",
                                           "-v{v}".format(v=original_version),
                                           "-DX-Mini-Buildd-Originally-Changed-By={a}".format(a=original_author).encode(mini_buildd.setup.CHAR_ENCODING)],
                                          cwd=dst_path,
                                          env=env,
                                          stdout=out,
                                          stderr=err)
                    mini_buildd.misc.log_call_output(LOG.warn, "dpkg-genchanges warning:", err)

            # Sign and add to incoming queue
            self.model.mbd_gnupg.sign(changes)
            self.incoming_queue.put(changes)
        except:
            t.close()
            raise

    def get_keyring_package(self):
        return KeyringPackage(self.model.identity,
                              self.model.mbd_gnupg,
                              self.model.mbd_fullname,
                              self.model.email_address)

    @classmethod
    def get_test_package(cls, id_):
        return DSTPackage("/usr/share/doc/mini-buildd/examples/packages/mbd-test-{i}".format(i=id_),
                          version=DebianVersion.stamp())

    def mbd_get_sources_list(self, codename, repo_regex, suite_regex, prefixes, with_extra_sources):
        apt_lines = []

        for r in mini_buildd.models.repository.Repository.objects.filter(identity__regex=r"^{r}$".format(r=repo_regex)):
            repo_info = "mini-buildd '{i}': Repository '{r}'".format(i=self.model.identity, r=r.identity)
            for d in r.distributions.all().filter(base_source__codename__exact=codename):
                if with_extra_sources:
                    apt_lines.append("# {i}: Extra sources".format(i=repo_info))
                    for e in d.extra_sources.all():
                        for p in prefixes:
                            apt_lines.append(e.source.mbd_get_apt_line(d, prefix=p))
                    apt_lines.append("")

                apt_lines.append("# {i}: Sources".format(i=repo_info))
                for s in r.layout.suiteoption_set.filter(suite__name__regex=r"^{r}$".format(r=suite_regex)):
                    for p in prefixes:
                        apt_lines.append(d.mbd_get_apt_line(r, s, prefix=p))
        return "\n".join(apt_lines) + "\n"


_INSTANCE = None


def get():
    assert _INSTANCE
    return _INSTANCE


if __name__ == "__main__":
    mini_buildd.misc.setup_console_logging()
    import doctest
    doctest.testmod()
