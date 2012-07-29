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
import StringIO
import pickle
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

    # May be used by any model for persistent python state
    pickled_data = django.db.models.TextField(blank=True, editable=False)

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

    def mbd_get_pickled_data(self, default=None):
        try:
            return pickle.load(StringIO.StringIO(self.pickled_data.encode("UTF-8")))
        except:
            return default

    def mbd_set_pickled_data(self, data):
        self.pickled_data = pickle.dumps(data)


class StatusModel(Model):
    """
    Abstract model for all models that carry a status.

    ============ =====================================
    Status       Semantic
    ============ =====================================
    0=unprepared Not prepared on the system.
    1=prepared   Prepared on system.
    2=active     Prepared on the system and activated.
    ============ =====================================

    Inheriting classes may overwrite the following hooks to
    control status handling.

    The pre-condition is guaranteed when called via the admin
    action methods defined here. The hooks must not be called
    directly (except for the Daemon model's "check" hook; it's
    called directly when the daemon is started implicitely on
    "mini-buildd" restarts or reloads).

    =========== ============== =========== =========== ============================================================================
    Action      Pre condition  On success  On failure  Hook semantic
    =========== ============== =========== =========== ============================================================================
    Prepare     <= unprepared  prepared    uprepared   Prepare the instance on the system; must not leave cruft around on failure.
    Unprepare   >= prepared    unprepared  prepared    Remove the instance from the system; should not change anything on failure.
    Check       >= prepared    UNCHANGED   prepared    Check the instance. Will be run prior to each activation action.
    Activate    >= prepared    active      UNCHANGED   Any additional actions on activation (used for Daemon model only).
    Deactivate  >= prepared    prepared    UNCHANGED   Any additional actions on deactivation (used for Daemon model only).
    =========== ============== =========== =========== ============================================================================
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
    auto_reactivate = django.db.models.BooleanField(default=False, editable=False)
    STATUS_COLORS = {
        STATUS_UNPREPARED: "yellow",
        STATUS_PREPARED: "blue",
        STATUS_ACTIVE: "green"}

    class Meta(Model.Meta):
        abstract = True

    class Admin(Model.Admin):
        @classmethod
        def action_unprepare_without_confirmation(cls, request, queryset):
            for o in queryset:
                if not o.mbd_is_prepared():
                    o.mbd_msg_info(request, "{o}: Already unprepared.".format(o=o))
                else:
                    try:
                        o.mbd_unprepare(request)
                        o.status = o.STATUS_UNPREPARED
                        o.save()
                        o.mbd_msg_info(request, "{o}: Unprepare successful.".format(o=o))
                    except Exception as e:
                        o.mbd_msg_error(request, "{o}: Unprepare FAILED: {e}.".format(o=o, e=str(e)))

        @classmethod
        def action_unprepare(cls, request, queryset):
            if request.POST.get("confirm"):
                cls.action_unprepare_without_confirmation(request, queryset)
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
                    current_app=cls.admin_site.name)

        def _action_unprepare(self, request, queryset):
            self.__class__.action_unprepare(request, queryset)
        _action_unprepare.short_description = "[1] Unprepare selected objects"

        @classmethod
        def action_deactivate(cls, request, queryset):
            for o in queryset:
                if not o.mbd_is_active():
                    o.mbd_msg_info(request, "{o}: Already deactivated.".format(o=o))
                else:
                    try:
                        o.mbd_deactivate(request)
                        o.status = o.STATUS_PREPARED
                        o.save()
                        o.mbd_msg_info(request, "{o}: Deactivate successful.".format(o=o))
                    except Exception as e:
                        o.mbd_msg_error(request, "{o}: Deactivate FAILED: {e}.".format(o=o, e=str(e)))

        def _action_deactivate(self, request, queryset):
            self.__class__.action_deactivate(request, queryset)
        _action_deactivate.short_description = "[2] Deactivate selected objects"

        @classmethod
        def action_prepare(cls, request, queryset):
            for o in queryset:
                if o.mbd_is_prepared():
                    o.mbd_msg_info(request, "{o}: Already prepared.".format(o=o))
                else:
                    try:
                        # Also run for all status dependencies
                        cls.action_prepare(request, o.mbd_get_status_dependencies())

                        o.mbd_prepare(request)
                        o.status = o.STATUS_PREPARED
                        o.save()
                        o.mbd_msg_info(request, "{o}: Prepare successful.".format(o=o))
                    except Exception as e:
                        o.mbd_msg_error(request, "{o}: Prepare FAILED: {e}.".format(o=o, e=str(e)))

        def _action_prepare(self, request, queryset):
            self.__class__.action_prepare(request, queryset)
        _action_prepare.short_description = "[3] Prepare selected objects and dependencies"

        @classmethod
        def action_activate(cls, request, queryset):
            for o in queryset:
                if o.mbd_is_active():
                    o.mbd_msg_info(request, "{o}: Already active.".format(o=o))
                else:
                    # Try to prepare implicitely if neccessary
                    if not o.mbd_is_prepared():
                        cls.action_prepare(request, (o,))

                    # Only try to activate if we are in status prepare
                    if o.mbd_is_prepared():
                        try:
                            # Also run for all status dependencies
                            cls.action_activate(request, o.mbd_get_status_dependencies())

                            # Always check before activation
                            cls.action_check(request, (o,))

                            o.mbd_activate(request)
                            o.status = o.STATUS_ACTIVE
                            o.auto_reactivate = False
                            o.save()
                            o.mbd_msg_info(request, "{o}: Activate successful.".format(o=o))
                        except Exception as e:
                            o.mbd_msg_error(request, "{o}: Activate FAILED: {e}.".format(o=o, e=str(e)))

        def _action_activate(self, request, queryset):
            self.__class__.action_activate(request, queryset)
        _action_activate.short_description = "[4] Activate selected objects and dependencies"

        @classmethod
        def action_check(cls, request, queryset):
            for o in queryset:
                if o.mbd_is_prepared():
                    try:
                        # Also run for all status dependencies
                        cls.action_check(request, o.mbd_get_status_dependencies())

                        o.mbd_check(request)
                        o.last_checked = datetime.datetime.now()
                        if o.auto_reactivate:
                            o.status = StatusModel.STATUS_ACTIVE
                            o.auto_reactivate = False
                        o.save()
                        o.mbd_msg_info(request, "{o}: Check successful.".format(o=o))
                    except Exception as e:
                        # Check failed, auto-deactivate this instance
                        o.status = StatusModel.STATUS_PREPARED
                        o.auto_reactivate = True
                        o.save()
                        o.mbd_msg_error(request, "{o}: Auto-Deactivating: Check FAILED: {e}.".format(o=o, e=str(e)))
                else:
                    o.mbd_msg_warn(request, "{o}: Skipped -- not prepared.".format(o=o))

        def _action_check(self, request, queryset):
            self.__class__.action_check(request, queryset)
        _action_check.short_description = "[5] Check selected objects and dependencies"

        def colored_status(self, obj):
            # [avoid pylint R0201]
            if self:
                pass

            return '<div style="foreground-color:black;background-color:{c};">{o}</div>'.format(o=obj.get_status_display(), c=obj.STATUS_COLORS[obj.status])
        colored_status.allow_tags = True

        actions = [_action_unprepare, _action_deactivate, _action_prepare, _action_activate, _action_check]
        list_display = ('colored_status', '__unicode__')

    def mbd_activate(self, request):
        "Per default, nothing is to be done on 'activate'."
        pass

    def mbd_deactivate(self, request):
        "Per default, nothing is to be done on 'deactivate'."
        pass

    def mbd_is_prepared(self):
        return self.status >= self.STATUS_PREPARED

    def mbd_is_active(self):
        return self.status >= self.STATUS_ACTIVE

    @classmethod
    def mbd_get_active(cls):
        return cls.objects.filter(status__gte=cls.STATUS_ACTIVE)

    @classmethod
    def mbd_get_active_or_auto_reactivate(cls):
        return cls.objects.filter(django.db.models.Q(status__gte=cls.STATUS_ACTIVE) | django.db.models.Q(auto_reactivate=True))

    @classmethod
    def mbd_get_prepared(cls):
        return cls.objects.filter(status__gte=cls.STATUS_PREPARED)

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
