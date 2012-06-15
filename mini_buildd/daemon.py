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

    max_parallel_builds = django.db.models.IntegerField(
        default=4,
        help_text="Maximum number of parallel builds.")

    sbuild_parallel = django.db.models.IntegerField(
        default=1,
        help_text="Degree of parallelism per build.")

    max_parallel_packages = django.db.models.IntegerField(
        default=10,
        help_text="Maximum number of parallel packages to process.")

    gnupg_template = django.db.models.TextField(default="""
Key-Type: DSA
Key-Length: 1024
Expire-Date: 0""")

    class Meta:
        verbose_name = "[D2] Daemon"
        verbose_name_plural = "[D2] Daemon"

    def __init__(self, *args, **kwargs):
        ".. todo:: GPG: to be replaced in template; Only as long as we dont know better"
        super(Daemon, self).__init__(*args, **kwargs)
        self.gnupg = gnupg.GnuPG(self.gnupg_template)
        self.incoming_queue = Queue.Queue(maxsize=self.max_parallel_packages)

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

django.contrib.admin.site.register(Daemon)

def run(dm):
    """.. todo:: Own GnuPG model """

    log.info("Preparing {d}".format(d=dm))
    dm.gnupg.prepare()

    builds = []

    log.info("Starting {d}".format(d=dm))
    while True:
        event = dm.incoming_queue.get()
        if event == "SHUTDOWN":
            break

        c = changes.Changes(event)
        r = c.get_repository()
        if c.is_buildrequest():
            log.info("{p}: Got build request for {r}".format(p=c.get_pkg_id(), r=r.id))
            builds.append(misc.run_as_thread(builder.run, br=c))
        elif c.is_buildresult():
            log.info("{p}: Got build result for {r}".format(p=c.get_pkg_id(), r=r.id))
            c.untar(path=r.mbd_get_incoming_path())
            r._reprepro.processincoming()
        else:
            log.info("{p}: Got user upload for {r}".format(p=c.get_pkg_id(), r=r.id))
            for br in c.gen_buildrequests():
                br.upload()

        dm.incoming_queue.task_done()

    for t in builds:
        log.debug("Waiting for {i}".format(i=t))
        t.join()

    log.info("Stopped {d}".format(d=dm))
