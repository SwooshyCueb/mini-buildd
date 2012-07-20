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

import urllib
import logging

import django.db.models
import django.contrib.messages
import django.contrib.admin
import django.contrib.auth.models
import django.db.models.signals
import django.core.exceptions
import django.template.response

import mini_buildd.misc

log = logging.getLogger(__name__)


def msg_info(request, msg):
    if request:
        django.contrib.messages.add_message(request, django.contrib.messages.INFO, msg)
    log.info(msg)


def msg_error(request, msg):
    if request:
        django.contrib.messages.add_message(request, django.contrib.messages.ERROR, msg)
    log.error(msg)


def msg_warn(request, msg):
    if request:
        django.contrib.messages.add_message(request, django.contrib.messages.WARNING, msg)
    log.warn(msg)


def action_delete(model, request, queryset):
    """Custom delete action.

    This workaround ensures that the model's delete() method is
    called (where we do important checks).
    Default actions do not call that ;(.
    See: https://docs.djangoproject.com/en/dev/ref/contrib/admin/actions/
    """
    for o in queryset:
        try:
            if getattr(o, "status", None) and o.status > o.STATUS_UNPREPARED:
                raise Exception(u"Unprepare first.")
            else:
                o.delete()
        except Exception as e:
            msg_error(request, u"Deletion failed for '{o}': {e}".format(o=o, e=e))
action_delete.short_description = "[0] Delete selected objects"

django.contrib.admin.site.disable_action("delete_selected")
django.contrib.admin.site.add_action(action_delete, "mini_buildd_delete")


class Model(django.db.models.Model):
    """Abstract father model for all mini-buildd models.

    This just makes sure no config is changed or deleted while
    the daemon is running.
    """
    class Meta:
        abstract = True

    def check_daemon_stopped(self):
        import mini_buildd.daemon
        if mini_buildd.daemon.get().is_running():
            raise django.core.exceptions.ValidationError(u"Please stop the Daemon first!")

    def delete(self):
        self.check_daemon_stopped()
        super(Model, self).delete()

    def clean(self):
        self.check_daemon_stopped()
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
        STATUS_PREPARED: "blue",
        STATUS_ACTIVE: "green"}

    class Meta:
        abstract = True

    class Admin(django.contrib.admin.ModelAdmin):
        @classmethod
        def action(cls, request, queryset, action, success_status, status_calc):
            for s in queryset:
                try:
                    # For prepare, activate, also run for all status dependencies
                    if status_calc == max:
                        cls.action(request, s.mbd_get_status_dependencies(), action, success_status, status_calc)

                    getattr(s, "mbd_" + action)(request)
                    s.status = status_calc(s.status, success_status)
                    s.save()
                    msg_info(request, "{s}: '{a}' successful".format(s=s, a=action))
                except Exception as e:
                    msg_error(request, "{s}: '{a}' FAILED: {e}".format(s=s, a=action, e=str(e)))

        def action_prepare(self, request, queryset):
            self.action(request, queryset, "prepare", StatusModel.STATUS_PREPARED, max)
        action_prepare.short_description = "[1] Prepare selected objects (and dependencies)"

        def action_unprepare(self, request, queryset):
            if request.POST.get("confirm"):
                self.action(request, queryset, "unprepare", StatusModel.STATUS_UNPREPARED, min)
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
                        "action_checkbox_name": django.contrib.admin.helpers.ACTION_CHECKBOX_NAME},
                    current_app=self.admin_site.name)
        action_unprepare.short_description = "[2] Unprepare selected objects"

        def action_activate(self, request, queryset):
            for s in queryset:
                # Prepare implicitely if neccessary
                if s.status < s.STATUS_PREPARED:
                    self.action_prepare(request, (s,))
                self.action(request, (s,), "activate", StatusModel.STATUS_ACTIVE, status_calc=max)
        action_activate.short_description = "[3] Activate selected objects"

        def action_deactivate(self, request, queryset):
            self.action(request, queryset, "deactivate", StatusModel.STATUS_PREPARED, status_calc=min)
        action_deactivate.short_description = "[4] Deactivate selected objects (and dependencies)"

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

    def mbd_get_status_dependencies(self):
        return []

    def mbd_check_status_dependencies(self, request=None, lower_status=0):
        msg_info(request, "Checking status deps for: {M} {S}".format(M=self.__class__.__name__, S=self))
        for d in self.mbd_get_status_dependencies():
            msg_info(request, "Checking dependency: {d}".format(d=d))
            if d.status < (self.status - lower_status):
                raise Exception("'{S}' has dependent instance '{d}' with insufficent status '{s}'".format(S=self, d=d, s=d.get_status_display()))
            d.mbd_check_status_dependencies(request, lower_status)

from mini_buildd import gnupg


class AptKey(gnupg.GnuPGPublicKey):
    pass
django.contrib.admin.site.register(AptKey, AptKey.Admin)


from mini_buildd import source


class Archive(source.Archive):
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
    may_upload_to = django.db.models.ManyToManyField(repository.Repository)

    class Admin(gnupg.GnuPGPublicKey.Admin):
        search_fields = gnupg.GnuPGPublicKey.Admin.search_fields + ["user"]
        readonly_fields = gnupg.GnuPGPublicKey.Admin.readonly_fields + ["user"]

    def __unicode__(self):
        return "User profile for '{u}'".format(u=self.user)

django.contrib.admin.site.register(UserProfile, UserProfile.Admin)


def create_user_profile(sender, instance, created, **kwargs):
    "Automatically create a user profile with every user that is created"
    if created:
        UserProfile.objects.create(user=instance)
django.db.models.signals.post_save.connect(create_user_profile, sender=django.contrib.auth.models.User)


class Remote(gnupg.GnuPGPublicKey):
    http = django.db.models.CharField(primary_key=True, max_length=255, default="")
    wake_command = django.db.models.CharField(max_length=255, default="", blank=True, help_text="For future use.")

    class Admin(gnupg.GnuPGPublicKey.Admin):
        search_fields = gnupg.GnuPGPublicKey.Admin.search_fields + ["http"]
        readonly_fields = gnupg.GnuPGPublicKey.Admin.readonly_fields + ["key", "key_id"]

    def __unicode__(self):
        try:
            return unicode(self.mbd_download_builder_state())
        except Exception as e:
            return "{h}: {e}".format(h=self.http, e=unicode(e))

    def mbd_prepare(self, r):
        url = "http://{h}/mini_buildd/download/archive.key".format(h=self.http)
        msg_info(r, "Downloading '{u}'...".format(u=url))
        self.key = urllib.urlopen(url).read()
        if self.key:
            msg_warn(r, "Downloaded remote key integrated: Please check key manually before activation!")
        else:
            raise Exception("Empty remote key from '{u}' -- maybe the remote is not prepared yet?".format(u=url))
        super(Remote, self).mbd_prepare(r)

    def mbd_download_builder_state(self):
        url = "http://{h}/mini_buildd/download/builder_state".format(h=self.http)
        status = urllib.urlopen(url)
        return mini_buildd.misc.BuilderState(file=status)

django.contrib.admin.site.register(Remote, Remote.Admin)
