# -*- coding: utf-8 -*-
import os
import contextlib
import logging

import django.db
import django.core.exceptions

from mini_buildd import changes

from mini_buildd.models import Repository

log = logging.getLogger(__name__)

class Dispatcher(django.db.models.Model):
    max_parallel_packages = django.db.models.IntegerField(
        default=10,
        help_text="Maximum number of parallel packages to process.")

    def __unicode__(self):
        res = "Dispatcher for: "
        for c in Repository.objects.all():
            res += c.__unicode__() + ", "
        return res

    def clean(self):
        super(Dispatcher, self).clean()
        if Dispatcher.objects.count() > 0 and self.id != Dispatcher.objects.get().id:
            raise django.core.exceptions.ValidationError("You can only create one Dispatcher instance!")

    def run(self, incoming_queue, build_queue):
        log.info("Preparing {d}".format(d=self))

        for r in Repository.objects.all():
            r.prepare()

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
