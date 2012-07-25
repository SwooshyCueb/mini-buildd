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

import datetime
import logging

import django.db.models
import django.contrib.messages
import django.contrib.admin
import django.contrib.auth.models
import django.db.models.signals
import django.core.exceptions
import django.template.response

LOG = logging.getLogger(__name__)


def action_delete(_model, request, queryset):
    """Custom delete action.

    This workaround ensures that the model's delete() method is
    called (where we do important checks).
    Default actions do not call that ;(.
    See: https://docs.djangoproject.com/en/dev/ref/contrib/admin/actions/
    """
    for o in queryset:
        try:
            o.delete()
        except Exception as e:
            o.mbd_msg_error(request, u"Deletion failed for '{o}': {e}".format(o=o, e=e))

action_delete.short_description = "[0] Delete selected objects"

try:
    django.contrib.admin.site.disable_action("delete_selected")
except:
    pass
django.contrib.admin.site.add_action(action_delete, "mini_buildd_delete")


class Model(django.db.models.Model):
    """Abstract father model for all mini-buildd models.

    This just makes sure no config is changed or deleted while
    the daemon is running.
    """
    extra_options = django.db.models.TextField(blank=True, editable=False,
                                               help_text="""\
Free form text that may be used by any real model for any extra
options to support without changing the database scheme.
""")

    class Meta:
        abstract = True
        app_label = "mini_buildd"

    class Admin(django.contrib.admin.ModelAdmin):
        pass

    def delete(self, *args, **kwargs):
        """
        Custom delete. Deny deletion if Daemon is running, or the instance is prepared.
        """
        self.mbd_check_daemon_stopped()

        is_prepared_func = getattr(self, "mbd_is_prepared", None)
        if is_prepared_func and is_prepared_func():
            raise Exception(u"Unprepare first.")

        super(Model, self).delete(*args, **kwargs)

    def clean(self, *args, **kwargs):
        self.mbd_check_daemon_stopped()
        super(Model, self).clean(*args, **kwargs)

    @classmethod
    def mbd_msg_info(cls, request, msg):
        if request:
            django.contrib.messages.add_message(request, django.contrib.messages.INFO, msg)
        LOG.info(msg)

    @classmethod
    def mbd_msg_error(cls, request, msg):
        if request:
            django.contrib.messages.add_message(request, django.contrib.messages.ERROR, msg)
        LOG.error(msg)

    @classmethod
    def mbd_msg_warn(cls, request, msg):
        if request:
            django.contrib.messages.add_message(request, django.contrib.messages.WARNING, msg)
        LOG.warn(msg)

    @classmethod
    def mbd_get_daemon(cls):
        import mini_buildd.daemon
        return mini_buildd.daemon.get()

    def mbd_check_daemon_stopped(self):
        if self.mbd_get_daemon().is_running():
            raise django.core.exceptions.ValidationError(u"Please stop the Daemon first!")


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
    status = django.db.models.IntegerField(choices=STATUS_CHOICES, default=STATUS_UNPREPARED, editable=False)
    last_checked = django.db.models.DateTimeField(default=datetime.datetime.min, editable=False)
    STATUS_COLORS = {
        STATUS_UNPREPARED: "yellow",
        STATUS_PREPARED: "blue",
        STATUS_ACTIVE: "green"}

    class Meta(Model.Meta):
        abstract = True

    class Admin(Model.Admin):
        @classmethod
        def action(cls, request, queryset, action, success_status, status_calc):
            for o in queryset:
                try:
                    if o.status != success_status:
                        # For prepare, activate, also run for all status dependencies
                        if status_calc == max:
                            cls.action(request, o.mbd_get_status_dependencies(), action, success_status, status_calc)

                        getattr(o, "mbd_" + action)(request)
                        o.status = status_calc(o.status, success_status)
                        o.save()
                        o.mbd_msg_info(request, "{o}: '{a}' successful.".format(o=o, a=action))
                    else:
                        o.mbd_msg_info(request, "{o}: Already in status '{s}'.".format(o=o, s=o.get_status_display()))
                except Exception as e:
                    o.mbd_msg_error(request, "{o}: '{a}' FAILED: {e}.".format(o=o, a=action, e=str(e)))

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
        action_unprepare.short_description = "[1] Unprepare selected objects"

        def action_deactivate(self, request, queryset):
            self.action(request, queryset, "deactivate", StatusModel.STATUS_PREPARED, status_calc=min)
        action_deactivate.short_description = "[2] Deactivate selected objects"

        def action_prepare(self, request, queryset):
            self.action(request, queryset, "prepare", StatusModel.STATUS_PREPARED, max)
        action_prepare.short_description = "[3] Prepare selected objects (and dependencies)"

        def action_activate(self, request, queryset):
            for s in queryset:
                # Prepare implicitely if neccessary
                if s.status < s.STATUS_PREPARED:
                    self.action_prepare(request, (s,))
                self.action(request, (s,), "activate", StatusModel.STATUS_ACTIVE, status_calc=max)
        action_activate.short_description = "[4] Activate selected objects"

        def action_check_and_update(self, request, queryset):
            # [avoid pylint R0201]
            if self:
                pass
            for o in queryset:
                if o.mbd_is_prepared():
                    try:
                        o.mbd_check_and_update(request)
                        o.last_checked = datetime.datetime.now()
                        o.save()
                        o.mbd_msg_info(request, "{o}: Check and update successful.".format(o=o))
                    except Exception as e:
                        # Check failed, deactivate this instance
                        o.status = StatusModel.STATUS_PREPARED
                        o.save()
                        o.mbd_msg_error(request, "{o}: Check and update FAILED: {e}.".format(o=o, e=str(e)))
                else:
                    o.mbd_msg_warn(request, "{o}: Skipped -- not prepared.".format(o=o))
        action_check_and_update.short_description = "[5] Check and update selected objects"

        def colored_status(self, obj):
            # [avoid pylint R0201]
            if self:
                pass

            return '<div style="foreground-color:black;background-color:{c};">{o}</div>'.format(o=obj.get_status_display(), c=obj.STATUS_COLORS[obj.status])
        colored_status.allow_tags = True

        actions = [action_unprepare, action_deactivate, action_prepare, action_activate, action_check_and_update]
        list_display = ('colored_status', '__unicode__')

    def mbd_activate(self, request):
        pass

    def mbd_deactivate(self, request):
        pass

    def mbd_check_and_update(self, request):
        self.mbd_msg_warn(request, "Model has no check_and_update method defined")

    def mbd_is_prepared(self):
        return self.status >= self.STATUS_PREPARED

    def mbd_is_active(self):
        return self.status >= self.STATUS_ACTIVE

    @classmethod
    def mbd_get_active(cls):
        return cls.objects.filter(status=cls.STATUS_ACTIVE)

    def mbd_get_status_display(self):
        return u"{s} [{c}]".format(s=self.get_status_display(), c=self.last_checked)

    def mbd_get_status_dependencies(self):
        LOG.debug("No status dependencies for {o}".format(o=self))
        return []

    def mbd_check_status_dependencies(self, request=None, lower_status=0):
        self.mbd_msg_info(request, "Checking status deps for: {M} {S}".format(M=self.__class__.__name__, S=self))
        for d in self.mbd_get_status_dependencies():
            self.mbd_msg_info(request, "Checking dependency: {d}".format(d=d))
            if d.status < (self.status - lower_status):
                raise Exception("'{S}' has dependent instance '{d}' with insufficent status '{s}'".format(S=self, d=d, s=d.get_status_display()))
            d.mbd_check_status_dependencies(request, lower_status)
