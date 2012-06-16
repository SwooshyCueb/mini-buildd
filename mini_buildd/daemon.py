# -*- coding: utf-8 -*-
import os, Queue, contextlib, socket, logging

import django.db, django.core.exceptions

from mini_buildd import misc, changes, gnupg, builder

from mini_buildd.models import Repository

log = logging.getLogger(__name__)

class Daemon(django.db.models.Model):
    fqdn = django.db.models.CharField(
        max_length=200,
        default=socket.getfqdn(),
        help_text="Fully qualified hostname.")

    gnupg_template = django.db.models.TextField(default="""
Key-Type: DSA
Key-Length: 2048
Expire-Date: 0
""")

    gnupg_keyserver = django.db.models.CharField(
        max_length=200,
        default="subkeys.pgp.net",
        help_text="GnuPG keyserver to use.")

    incoming_queue_size = django.db.models.SmallIntegerField(
        default=2*misc.get_cpus(),
        help_text="Maximum number of parallel packages to process.")

    build_queue_size = django.db.models.SmallIntegerField(
        default=misc.get_cpus(),
        help_text="Maximum number of parallel builds.")

    sbuild_jobs = django.db.models.SmallIntegerField(
        default=1,
        help_text="Degree of parallelism per build (via sbuild's '--jobs' option).")

    class Meta:
        verbose_name = "[D2] Daemon"
        verbose_name_plural = "[D2] Daemon"

    class Admin(django.contrib.admin.ModelAdmin):
        fieldsets = (
            ("Basics", {
                    "fields": ("fqdn", "gnupg_template", "gnupg_keyserver")
                    }),
            ("Manager Options", {
                    "fields": ("incoming_queue_size",)
                    }),
            ("Builder Options", {
                    "fields": ("build_queue_size", "sbuild_jobs")
                    }),)

    def __init__(self, *args, **kwargs):
        ".. todo:: GPG: to be replaced in template; Only as long as we don't know better"
        super(Daemon, self).__init__(*args, **kwargs)
        self._gnupg = gnupg.GnuPG(self.gnupg_template)
        self._incoming_queue = Queue.Queue(maxsize=self.incoming_queue_size)
        self._build_queue = Queue.Queue(maxsize=self.build_queue_size)
        self._packages = {}

    def __unicode__(self):
        res = "Daemon for: "
        for c in Repository.objects.all():
            res += c.__unicode__() + ", "
        return res

    def clean(self):
        super(Daemon, self).clean()
        if Daemon.objects.count() > 0 and self.id != Daemon.objects.get().id:
            raise django.core.exceptions.ValidationError("You can only create one Daemon instance!")

    def mbd_get_pub_key(self):
        return self._gnupg.get_pub_key()

    def mbd_get_dput_conf(self):
        return """\
[mini-buildd-{h}]
method   = ftp
fqdn     = {fqdn}:{p}
login    = anonymous
incoming = /incoming
""".format(h=self.fqdn.split(".")[0], fqdn=self.fqdn, p=8067)

django.contrib.admin.site.register(Daemon, Daemon.Admin)

def get():
    dm, created = Daemon.objects.get_or_create(id=1)
    if created:
        log.info("New default Daemon model instance created")
    return dm

class Package(object):
    DONE = 0
    INCOMPLETE = 1

    def __init__(self, changes):
        self.changes = changes
        self.pid = changes.get_pkg_id()
        self.repository = changes.get_repository()
        self.requests = self.changes.gen_buildrequests()
        self.success = {}
        self.failed = {}
        self.request_missing_builds()

    def request_missing_builds(self):
        log.info(self.requests)
        for key, r in self.requests.items():
            log.info(str(key))
            log.info(repr(r))
            if key not in self.success:
                r.upload()

    def update(self, result):
        arch = result["Sbuild-Architecture"]
        status = result["Sbuild-Status"]
        log.info("{p}: Got build result for '{a}': {s}".format(p=self.pid, a=arch, s=status))

        if status == "success" or status == "skipped":
            self.success[arch] = result
        else:
            self.failed[arch] = result

        missing = len(self.requests) - len(self.success) - len(self.failed)
        if missing > 0:
            log.debug("{p}: {n} arches still missing.".format(p=self.pid, n=missing))
            return self.INCOMPLETE

        # Finish up
        log.info("{p}: All build results received".format(p=self.pid))
        try:
            if self.failed:
                raise Exception("{p}: {n} archs failed".format(p=self.pid, n=len(self.failed)))

            for arch, c in self.success.items():
                c.untar(path=self.repository.mbd_get_incoming_path())
                self.repository._reprepro.processincoming()
        except Exception as e:
            log.error(str(e))
            # todo Error!
        finally:
            for arch, c in self.success.items() + self.failed.items():
                c.archive()
            #for arch, c in self.failed.items():
            #    c.archive()
            self.changes.archive()
        return self.DONE

def run(dm):
    """.. todo:: Own GnuPG model """
    dm._gnupg.prepare()

    # Start builder
    builder_thread = misc.run_as_thread(builder.run, build_queue=dm._build_queue, sbuild_jobs=dm.sbuild_jobs)

    while True:
        log.info("Status: {0} active packages, {0} changes waiting in incoming.".
                 format(len(dm._packages), dm._incoming_queue.qsize()))

        event = dm._incoming_queue.get()
        if event == "SHUTDOWN":
            dm._build_queue.put("SHUTDOWN")
            break

        c = changes.Changes(event)
        pid = c.get_pkg_id()
        if c.is_buildrequest():
            dm._build_queue.put(event)
        elif c.is_buildresult():
            if dm._packages[pid].update(c) == Package.DONE:
                del dm._packages[pid]
        else:
            dm._packages[pid] = Package(c)

        dm._incoming_queue.task_done()

    builder_thread.join()
