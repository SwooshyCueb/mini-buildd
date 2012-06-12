# -*- coding: utf-8 -*-
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

class PrioSource(source.PrioSource):
    pass


class Suite(django.db.models.Model):
    name = django.db.models.CharField(
        primary_key=True, max_length=50,
        help_text="A suite to support, usually s.th. like 'unstable','testing' or 'stable'.")
    mandatory_version = django.db.models.CharField(
        max_length=50, default="~{rid}{nbv}+[1-9]",
        help_text="Mandatory version template; {rid}=repository id, {nbv}=numerical base distribution version.")

    migrates_from = django.db.models.ForeignKey(
        'self', blank=True, null=True,
        help_text="Leave this blank to make this suite uploadable, or chose a suite where this migrates from.")
    not_automatic = django.db.models.BooleanField(default=True)
    but_automatic_upgrades = django.db.models.BooleanField(default=False)

    def __unicode__(self):
        return self.name + " (" + ("<= " + self.migrates_from.name if self.migrates_from else "uploadable") + ")"

django.contrib.admin.site.register(Suite)


class Layout(django.db.models.Model):
    name = django.db.models.CharField(primary_key=True, max_length=128,
                            help_text="Name for the layout.")
    suites = django.db.models.ManyToManyField(Suite)

    def __unicode__(self):
        return self.name

django.contrib.admin.site.register(Layout)


class Distribution(django.db.models.Model):
    """
    .. todo:: Distribution Model

       - limit to distribution?  limit_choices_to={'codename': 'sid'})
       - how to limit to source.kind?
    """
    base_source = django.db.models.ForeignKey(Source, primary_key=True)

    extra_sources = django.db.models.ManyToManyField(PrioSource, blank=True, null=True)

    def __unicode__(self):
        ".. todo:: somehow indicate extra sources to visible name"
        return self.base_source.origin + ": " + self.base_source.codename

    def mbd_get_apt_sources_list(self):
        res = "# Base: {p}\n".format(p=self.base_source.mbd_get_apt_pin())
        res += self.base_source.mbd_get_apt_line() + "\n\n"
        for e in self.extra_sources.all():
            res += "# Extra: {p}\n".format(p=e.source.mbd_get_apt_pin())
            res += e.source.mbd_get_apt_line() + "\n"
        return res


django.contrib.admin.site.register(Distribution)

from mini_buildd import repository
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

    def __unicode__(self):
        return "Remote: {h}".format(h=self.host)

django.contrib.admin.site.register(Remote)
