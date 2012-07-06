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
  allow_emails_to

To group fields together for the end user, use AdminModel's *fieldset* option.

Methods
-------

Methods that represent mini-buildd logic should go into the
models directly, but must be prefixed with "mbd_". This avoids
conflicts with method names form the django model's class, but
still keeps the logic where it belongs.
"""

import os, datetime, socket, urllib, logging

import django.db.models, django.contrib.admin, django.contrib.auth.models, django.db.models.signals, django.contrib.messages, django.core.exceptions, django.template.response

import debian.deb822

log = logging.getLogger(__name__)

def msg_info(request, msg):
    if request: django.contrib.messages.add_message(request, django.contrib.messages.INFO, msg)
    log.info(msg)

def msg_error(request, msg):
    if request: django.contrib.messages.add_message(request, django.contrib.messages.ERROR, msg)
    log.error(msg)

def msg_warn(request, msg):
    if request: django.contrib.messages.add_message(request, django.contrib.messages.WARNING, msg)
    log.warn(msg)

class Model(django.db.models.Model):
    """Abstract father model for all mini-buildd models.

    - Make sure no config is saved while the daemon is running.
    """
    class Meta:
        abstract = True

    def clean(self):
        import daemon
        if daemon.get().is_running():
            raise django.core.exceptions.ValidationError(u"""Please deactivate the Daemon instance to change any configuration!""")
        super(Model, self).clean()

class StatusModel(Model):
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
    STATUS_UNPREPARED = 0
    STATUS_PREPARED = 1
    STATUS_ACTIVE = 2
    STATUS_CHOICES = (
        (STATUS_UNPREPARED, 'Unprepared'),
        (STATUS_PREPARED, 'Prepared'),
        (STATUS_ACTIVE, 'Active'))
    status = django.db.models.SmallIntegerField(choices=STATUS_CHOICES, default=STATUS_UNPREPARED)
    STATUS_COLORS = {
        STATUS_UNPREPARED: "yellow",
        STATUS_PREPARED:"blue",
        STATUS_ACTIVE: "green" }

    class Meta:
        abstract = True

    class Admin(django.contrib.admin.ModelAdmin):
        def action(self, request, queryset, action, success_status):
            for s in queryset:
                try:
                    getattr(s, "mbd_" + action)(request)
                    s.status = success_status
                    s.save()
                    msg_info(request, "{s}: '{a}' successful".format(s=s, a=action))
                except Exception as e:
                    msg_error(request, "{s}: '{a}' FAILED: {e}".format(s=s, a=action, e=str(e)))

        def action_prepare(self, request, queryset):
            self.action(request, queryset, "prepare", StatusModel.STATUS_PREPARED)
        action_prepare.short_description = "mini-buildd: 1 Prepare selected objects"

        def action_activate(self, request, queryset):
            for s in queryset:
                # Prepare implicitely if neccessary
                if s.status < s.STATUS_PREPARED:
                    self.action_prepare(request, (s,))
                if s.status >= s.STATUS_PREPARED:
                    self.action(request, (s,), "activate", StatusModel.STATUS_ACTIVE)
        action_activate.short_description = "mini-buildd: 2 Activate selected objects"

        def action_deactivate(self, request, queryset):
            for s in queryset:
                if s.status >= s.STATUS_ACTIVE:
                    self.action(request, (s,), "deactivate", StatusModel.STATUS_PREPARED)
                else:
                    msg_info(request, "{s}: Already deactivated".format(s=s))
        action_deactivate.short_description = "mini-buildd: 3 Deactivate selected objects"

        def action_unprepare(self, request, queryset):
            if request.POST.get("confirm"):
                self.action(request, queryset, "unprepare", StatusModel.STATUS_UNPREPARED)
            else:
                return django.template.response.TemplateResponse(
                    request,
                    "admin/confirm.html",
                    {
                        "title": ("Are you sure?"),
                        "queryset": queryset,
                        "action": "action_unprepare",
                        "desc": """\
Unpreparing means all the data associated by preparation will be
removed from the system. Especially for repositories,
this would mean losing all packages!
""",
                        "action_checkbox_name": django.contrib.admin.helpers.ACTION_CHECKBOX_NAME },
                    current_app=self.admin_site.name)
        action_unprepare.short_description = "mini-buildd: 4 Unprepare selected objects"

        def colored_status(self, o):
            return '<div style="foreground-color:black;background-color:{c};">{o}</div>'.format(o=o.get_status_display(), c=o.STATUS_COLORS[o.status])
        colored_status.allow_tags = True

        actions = [action_prepare, action_unprepare, action_activate, action_deactivate]
        search_fields = ["status"]
        readonly_fields = ["status"]
        list_display = ('colored_status', '__unicode__')

    def mbd_activate(self, request):
        pass

    def mbd_deactivate(self, request):
        pass

from mini_buildd import gnupg
class AptKey(gnupg.GnuPGPublicKey):
    pass
django.contrib.admin.site.register(AptKey, AptKey.Admin)

class UserKey(gnupg.GnuPGPublicKey):
    pass
django.contrib.admin.site.register(UserKey, UserKey.Admin)

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
class EmailAddress(repository.EmailAddress):
    pass
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


class UserProfile(gnupg.GnuPGPublicKey):
    user = django.db.models.OneToOneField(django.contrib.auth.models.User)

    class Admin(gnupg.GnuPGPublicKey.Admin):
        search_fields = gnupg.GnuPGPublicKey.Admin.search_fields + ["user"]
        readonly_fields = gnupg.GnuPGPublicKey.Admin.readonly_fields + ["user"]

    def __unicode__(self):
        return "User profile for '{u}'".format(u=self.user)

    # mini_buildd extra fields
    may_upload_to = django.db.models.ManyToManyField(Repository)

django.contrib.admin.site.register(UserProfile, UserProfile.Admin)

# Automatically create a user profile with every user that is created
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)
django.db.models.signals.post_save.connect(create_user_profile, sender=django.contrib.auth.models.User)


class Remote(gnupg.GnuPGPublicKey):
    http = django.db.models.CharField(primary_key=True, max_length=255, default="")

    class Admin(gnupg.GnuPGPublicKey.Admin):
        search_fields = gnupg.GnuPGPublicKey.Admin.search_fields + ["http"]
        readonly_fields = gnupg.GnuPGPublicKey.Admin.readonly_fields + ["key", "key_id"]

    def __unicode__(self):
        return self.http

    def mbd_prepare(self, r):
        url = "http://{h}/mini_buildd/download/archive.key".format(h=self.http)
        msg_info(r, "Downloading '{u}'...".format(u=url))
        self.key = urllib.urlopen(url).read()
        if self.key:
            msg_info(r, "Remote key integrated -- please check key manually before activation!")
        else:
            raise Exception("Empty remote key from '{u}' -- maybe the remote is not prepared yet?".format(u=url))
        super(Remote, self).mbd_prepare(r)

django.contrib.admin.site.register(Remote, Remote.Admin)
