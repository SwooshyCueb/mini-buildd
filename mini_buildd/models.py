# -*- coding: utf-8 -*-
"""
Generic module for models of the django application *mini_buildd*::

  from mini_buildd import models

Most models are split into separate modules, but we keep pseudo
declarations for all models here for convenience.

Naming conventions
==================

Model class and field names
---------------------------
All model class names and all field names must be **human
readable with no abbrevations** (as django, per default,
displays the internal names intelligently to the end user).

*Model class names* must be in **CamelCase**.

*Field names* must be all **lowercase** and **seperatedy by underscores**.

For example, **don't** try to do sort of "grouping" using names like::

  email_smtpserver
  email_allow_regex

This should rather read::

  smtp_server
  allow_email_to

To group fields together for the end user, use AdminModel's *fieldset* option.

Methods
-------

Methods that represent mini-buildd logic should go into the
models directly, but must be prefixed with "mbd_". This avoids
conflicts with method names form the django model's class, but
still keeps the logic where it belongs.
"""

import os, datetime, socket, urllib, logging

import django.db.models, django.contrib.admin, django.contrib.messages

import debian.deb822

log = logging.getLogger(__name__)

def msg_info(request, msg):
    django.contrib.messages.add_message(request, django.contrib.messages.INFO, msg)
    log.info(msg)

def msg_error(request, msg):
    django.contrib.messages.add_message(request, django.contrib.messages.ERROR, msg)
    log.error(msg)

def msg_warn(request, msg):
    django.contrib.messages.add_message(request, django.contrib.messages.WARNING, msg)
    log.warn(msg)

class EmailAddress(django.db.models.Model):
    address = django.db.models.EmailField(
        primary_key=True,
        max_length=254,
        help_text="E-Mail address.")

    class Meta:
        verbose_name_plural = "Email addresses"

    def __unicode__(self):
        return self.address

django.contrib.admin.site.register(EmailAddress)

class StatusModel(django.db.models.Model):
    """
    Abstract model for all models that carry a status.

    ========== =====================================
    Status     Desc
    ========== =====================================
    error      Unknown error state.
    unprepared Not prepared on the system.
    prepared   Prepared on system.
    active     Prepared on the system and activated.
    ========== =====================================
    """
    STATUS_ERROR = -1
    STATUS_UNPREPARED = 0
    STATUS_PREPARED = 1
    STATUS_ACTIVE = 2
    STATUS_CHOICES = (
        (STATUS_ERROR, 'Error'),
        (STATUS_UNPREPARED, 'Unprepared'),
        (STATUS_PREPARED, 'Prepared'),
        (STATUS_ACTIVE, 'Active'))
    status = django.db.models.SmallIntegerField(choices=STATUS_CHOICES, default=STATUS_UNPREPARED)
    STATUS_COLORS = {
        STATUS_ERROR: "red",
        STATUS_UNPREPARED: "yellow",
        STATUS_PREPARED:"blue",
        STATUS_ACTIVE: "green" }

    class Meta:
        abstract = True

    class Admin(django.contrib.admin.ModelAdmin):
        def action(self, request, queryset, action, success_status):
            for s in queryset:
                msg_info(request, "{s}: Running '{a}'".format(s=s, a=action))
                try:
                    getattr(s, "mbd_" + action)(request)
                    s.status = success_status
                    s.save()
                    msg_info(request, "{s}: '{a}' successful".format(s=s, a=action))
                except Exception as e:
                    s.status = s.STATUS_ERROR
                    s.__last_error = str(e)
                    msg_error(request, "Run failed: {a}={e}".format(a=action, e=str(e)))

        def action_prepare(self, request, queryset):
            self.action(request, queryset, "prepare", StatusModel.STATUS_PREPARED)
        action_prepare.short_description = "mini-buildd: 1 Prepare selected objects"

        def action_activate(self, request, queryset):
            for s in queryset:
                # Prepare implicitely if neccessary
                if s.status < s.STATUS_PREPARED:
                    self.action_prepare(request, (s,))

                if s.status >= s.STATUS_PREPARED:
                    s.status = s.STATUS_ACTIVE
                    s.save()
                    msg_info(request, "{s}: Activated".format(s=s))
        action_activate.short_description = "mini-buildd: 2 Activate selected objects"

        def action_deactivate(self, request, queryset):
            for s in queryset:
                if s.status >= s.STATUS_ACTIVE:
                    s.status = s.STATUS_PREPARED
                    s.save()
                    msg_info(request, "{s}: Deactivated".format(s=s))
                else:
                    msg_info(request, "{s}: Already deactivated".format(s=s))
        action_deactivate.short_description = "mini-buildd: 3 Deactivate selected objects"

        def action_unprepare(self, request, queryset):
            self.action(request, queryset, "unprepare", StatusModel.STATUS_UNPREPARED)
        action_unprepare.short_description = "mini-buildd: 4 Unprepare selected objects"

        def colored_status(self, o):
            return '<div style="foreground-color:black;background-color:{c};">{o}</div>'.format(o=o.get_status_display(), c=o.STATUS_COLORS[o.status])
        colored_status.allow_tags = True

        actions = [action_prepare, action_unprepare, action_activate, action_deactivate]
        search_fields = ["status"]
        readonly_fields = ["status"]
        list_display = ('colored_status', '__unicode__')


from mini_buildd import source
class Mirror(source.Mirror):
    pass
class Architecture(source.Architecture):
    pass
class Component(source.Component):
    pass
class Source(source.Source):
    pass
class PrioritySource(source.PrioritySource):
    pass


from mini_buildd import repository
class Suite(repository.Suite):
    pass
class Layout(repository.Layout):
    pass
class Distribution(repository.Distribution):
    pass
class Repository(repository.Repository):
    pass


from mini_buildd import chroot
class Chroot(chroot.Chroot):
    pass
class FileChroot(chroot.FileChroot):
    pass
class LVMChroot(chroot.LVMChroot):
    pass
class LoopLVMChroot(chroot.LoopLVMChroot):
    pass


from mini_buildd import daemon
class Daemon(daemon.Daemon):
    pass


class Remote(django.db.models.Model):
    host = django.db.models.CharField(max_length=99, default=socket.getfqdn())

    class Meta:
        verbose_name = "[D1] Remote"

    def __unicode__(self):
        return "Remote: {h}".format(h=self.host)

django.contrib.admin.site.register(Remote)
