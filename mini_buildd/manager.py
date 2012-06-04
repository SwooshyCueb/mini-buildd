# -*- coding: utf-8 -*-
import os, contextlib, logging

import django.db, django.core.exceptions

from mini_buildd import changes, gnupg

from mini_buildd.models import Repository

log = logging.getLogger(__name__)

class Manager(django.db.models.Model):
    max_parallel_packages = django.db.models.IntegerField(
        default=10,
        help_text="Maximum number of parallel packages to process.")

    gnupg_template = django.db.models.TextField(default="""
Key-Type: DSA
Key-Length: 1024
Expire-Date: 0""")

    def __init__(self, *args, **kwargs):
        ".. todo:: GPG: to be replaced in template; Only as long as we dont know better"
        super(Manager, self).__init__(*args, **kwargs)
        self.gnupg = gnupg.GnuPG(self.gnupg_template)

    def __unicode__(self):
        res = "Manager for: "
        for c in Repository.objects.all():
            res += c.__unicode__() + ", "
        return res

    def clean(self):
        super(Manager, self).clean()
        if Manager.objects.count() > 0 and self.id != Manager.objects.get().id:
            raise django.core.exceptions.ValidationError("You can only create one Manager instance!")

    def prepare(self):
        self.gnupg.prepare()
        for r in Repository.objects.all():
            r.prepare()

    def run(self, incoming_queue, build_queue):
        log.info("Preparing {d}".format(d=self))
        self.prepare()

        log.info("Starting {d}".format(d=self))
        while True:
            event = incoming_queue.get()
            if event == "SHUTDOWN":
                break

            c = changes.Changes(event)
            r = c.get_repository()
            if c.is_buildrequest():
                log.info("{p}: Got build request for {r}".format(p=c.get_pkg_id(), r=r.id))
                build_queue.put(event)
            elif c.is_buildresult():
                log.info("{p}: Got build result for {r}".format(p=c.get_pkg_id(), r=r.id))
                c.untar(path=r.get_incoming_path())
                r._reprepro.processincoming()
            else:
                log.info("{p}: Got user upload for {r}".format(p=c.get_pkg_id(), r=r.id))
                for br in c.gen_buildrequests():
                    br.upload()

            incoming_queue.task_done()

        log.info("Stopped {d}".format(d=self))
