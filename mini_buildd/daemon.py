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
        self.gnupg = gnupg.GnuPG(self.gnupg_template)
        self.incoming_queue = Queue.Queue(maxsize=self.incoming_queue_size)
        self.build_queue = Queue.Queue(maxsize=self.build_queue_size)

    def __unicode__(self):
        res = "Daemon for: "
        for c in Repository.objects.all():
            res += c.__unicode__() + ", "
        return res

    def clean(self):
        super(Daemon, self).clean()
        if Daemon.objects.count() > 0 and self.id != Daemon.objects.get().id:
            raise django.core.exceptions.ValidationError("You can only create one Daemon instance!")

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

def run(dm):
    """.. todo:: Own GnuPG model """
    dm.gnupg.prepare()

    # Start builder
    builder_thread = misc.run_as_thread(builder.run, build_queue=dm.build_queue, sbuild_jobs=dm.sbuild_jobs)

    while True:
        event = dm.incoming_queue.get()
        if event == "SHUTDOWN":
            dm.build_queue.put("SHUTDOWN")
            break

        c = changes.Changes(event)
        r = c.get_repository()
        if c.is_buildrequest():
            log.info("{p}: Got build request for {r}".format(p=c.get_pkg_id(), r=r.id))
            # This may block
            dm.build_queue.put(event)
        elif c.is_buildresult():
            log.info("{p}: Got build result for {r}".format(p=c.get_pkg_id(), r=r.id))
            c.untar(path=r.mbd_get_incoming_path())
            r._reprepro.processincoming()
        else:
            log.info("{p}: Got user upload for {r}".format(p=c.get_pkg_id(), r=r.id))
            for br in c.gen_buildrequests():
                br.upload()

        dm.incoming_queue.task_done()

    builder_thread.join()
