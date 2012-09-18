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
models directly, but must be prefixed with "mbd\_". This avoids
conflicts with method names form the django model's class, but
still keeps the logic where it belongs.
"""
from __future__ import unicode_literals

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

import mini_buildd.setup

LOG = logging.getLogger(__name__)


# Default action 'delete_selected' action does not call
# custom delete, nor does it ask prior to deletion.
#
# See: https://docs.djangoproject.com/en/dev/ref/contrib/admin/actions/
#
# So we just disable this default action. You can still delete
# single objects from the model's form.
try:
    django.contrib.admin.site.disable_action("delete_selected")
except:
    pass


class Model(django.db.models.Model):
    """Abstract father model for all mini-buildd models.

    This just makes sure no config is changed or deleted while
    the daemon is running.
    """
    extra_options = django.db.models.TextField(blank=True, editable=True,
                                               help_text="""\
Extra/experimental options (in the form 'KEY: VALUE' per line) a
model might support.

Note that this is basically just a workaround to easily add
options to a model without changing the database scheme; i.e.,
these options may best be described as a staging area, or list
of 'unofficial features'.

The resp. model documentation should describe what extra options
are actually supported by the current model.
""")

    # May be used by any model for persistent python state
    pickled_data = django.db.models.TextField(blank=True, editable=False)

    class Meta:
        abstract = True
        app_label = "mini_buildd"

    class Admin(django.contrib.admin.ModelAdmin):
        def save_model(self, request, obj, form, change):
            try:
                obj.mbd_get_daemon().stop(request=request)

                obj.save()
            except Exception as e:
                obj.mbd_msg_error(request, "Saving model failed: {e}.".format(e=e))
            finally:
                obj.mbd_get_daemon().restart(request=request)

        def delete_model(self, request, obj):
            try:
                obj.mbd_get_daemon().stop(request=request)

                is_prepared_func = getattr(obj, "mbd_is_prepared", None)
                if is_prepared_func and is_prepared_func():
                    self.mbd_unprepare(request, obj)

                obj.delete()
            except Exception as e:
                obj.mbd_msg_error(request, "Saving model failed: {e}.".format(e=e))
            finally:
                obj.mbd_get_daemon().restart(request=request)

    @classmethod
    def mbd_msg_info(cls, request, msg):
        if request:
            django.contrib.messages.add_message(request, django.contrib.messages.INFO, msg)
        LOG.info(msg)

    @classmethod
    def mbd_msg_warn(cls, request, msg):
        if request:
            django.contrib.messages.add_message(request, django.contrib.messages.WARNING, msg)
        LOG.warn(msg)

    @classmethod
    def mbd_msg_error(cls, request, msg):
        if request:
            django.contrib.messages.add_message(request, django.contrib.messages.ERROR, msg)
        LOG.error(msg)

    @classmethod
    def mbd_msg_exception(cls, request, msg, exception):
        if request:
            django.contrib.messages.add_message(request, django.contrib.messages.ERROR, "{m}: {e}".format(m=msg, e=exception))
        mini_buildd.setup.log_exception(LOG, msg, exception)

    @classmethod
    def mbd_get_daemon(cls):
        import mini_buildd.daemon
        return mini_buildd.daemon.get()

    def mbd_get_extra_option(self, key, default=None):
        for line in self.extra_options.splitlines():
            lkey, _lsep, lvalue = line.partition(":")
            if lkey == key:
                return lvalue.lstrip()
        return default

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
        STATUS_UNPREPARED: {"bg": "yellow", "fg": "black"},
        STATUS_PREPARED: {"bg": "blue", "fg": "white"},
        STATUS_ACTIVE: {"bg": "green", "fg": "white"}}

    class Meta(Model.Meta):
        abstract = True

    class Admin(Model.Admin):
        @classmethod
        def mbd_prepare(cls, request, obj):
            if obj.mbd_is_prepared():
                obj.mbd_msg_info(request, "{o}: Already prepared.".format(o=obj))
            else:
                # Also run for all status dependencies
                for o in obj.mbd_get_status_dependencies():
                    cls.mbd_prepare(request, o)

                obj.mbd_prepare(request)
                obj.status = obj.STATUS_PREPARED
                obj.save()
                obj.mbd_msg_info(request, "{o}: Prepare successful.".format(o=obj))

        @classmethod
        def mbd_activate(cls, request, obj):
            if obj.mbd_is_active():
                obj.mbd_msg_info(request, "{o}: Already active.".format(o=obj))
            else:
                # Try to prepare implicitely if neccessary
                if not obj.mbd_is_prepared():
                    cls.mbd_prepare(request, obj)

                # Also run for all status dependencies
                for o in obj.mbd_get_status_dependencies():
                    cls.mbd_activate(request, o)

                # Always check before activation
                cls.mbd_check(request, obj)

                obj.mbd_activate(request)
                obj.status = obj.STATUS_ACTIVE
                obj.auto_reactivate = False
                obj.save()
                obj.mbd_msg_info(request, "{o}: Activate successful.".format(o=obj))

        @classmethod
        def mbd_unprepare(cls, request, obj):
            if not obj.mbd_is_prepared():
                obj.mbd_msg_info(request, "{o}: Already unprepared.".format(o=obj))
            else:
                obj.mbd_unprepare(request)
                obj.status = obj.STATUS_UNPREPARED
                obj.last_checked = datetime.datetime.min
                obj.save()
                obj.mbd_msg_info(request, "{o}: Unprepare successful.".format(o=obj))

        @classmethod
        def mbd_deactivate(cls, request, obj):
            if not obj.mbd_is_active():
                obj.mbd_msg_info(request, "{o}: Already deactivated.".format(o=obj))
            else:
                obj.mbd_deactivate(request)
                obj.status = obj.STATUS_PREPARED
                obj.save()
                obj.mbd_msg_info(request, "{o}: Deactivate successful.".format(o=obj))

        @classmethod
        def mbd_check(cls, request, obj):
            if obj.mbd_is_prepared():
                try:
                    # Also run for all status dependencies
                    for o in obj.mbd_get_status_dependencies():
                        cls.mbd_check(request, o)

                    obj.mbd_check(request)
                    obj.last_checked = datetime.datetime.now()
                    if obj.auto_reactivate:
                        obj.status = StatusModel.STATUS_ACTIVE
                        obj.auto_reactivate = False
                    obj.save()
                    obj.mbd_msg_info(request, "{o}: Check successful.".format(o=obj))
                except:
                    # Check failed, auto-deactivate and re-raise exception
                    if obj.mbd_is_active():
                        obj.status = StatusModel.STATUS_PREPARED
                        obj.auto_reactivate = True
                        obj.save()
                        obj.mbd_msg_error(request, "{o}: Automatically deactivated.".format(o=obj))
                    raise
            else:
                raise Exception("{o}: Can't check unprepared object.".format(o=obj))

        @classmethod
        def mbd_action(cls, request, queryset, action):
            """
            Try to run action on each object in queryset, and
            emit error message on failure.
            """
            for o in queryset:
                try:
                    getattr(cls, "mbd_" + action)(request, o)
                except Exception as e:
                    o.mbd_msg_exception(request, "{o}: {a} failed".format(o=o, a=action), e)

        def mbd_action_prepare(self, request, queryset):
            self.mbd_action(request, queryset, "prepare")
        mbd_action_prepare.short_description = "Prepare"

        def mbd_action_activate(self, request, queryset):
            self.mbd_action(request, queryset, "activate")
        mbd_action_activate.short_description = "Activate"

        def mbd_action_unprepare(self, request, queryset):
            if request.POST.get("confirm"):
                self.mbd_action(request, queryset, "unprepare")
            else:
                return django.template.response.TemplateResponse(
                    request,
                    "admin/confirm.html",
                    {
                        "title": ("Are you sure?"),
                        "queryset": queryset,
                        "action": "mbd_action_unprepare",
                        "desc": """\
Unpreparing means all the data associated by preparation will be
removed from the system. Especially for repositories,
this would mean losing all packages!
""",
                        "action_checkbox_name": django.contrib.admin.helpers.ACTION_CHECKBOX_NAME},
                    current_app=self.admin_site.name)
        mbd_action_unprepare.short_description = "Unprepare"

        def mbd_action_deactivate(self, request, queryset):
            self.mbd_action(request, queryset, "deactivate")
        mbd_action_deactivate.short_description = "Deactivate"

        def mbd_action_check(self, request, queryset):
            self.mbd_action(request, queryset, "check")
        mbd_action_check.short_description = "Check"

# pylint: disable=R0201
        def colored_status(self, obj):
            return '<div style="background-color:{bc};color:{fc};padding:2px 0px 2px 5px">{o}</div>'.format(
                bc=obj.STATUS_COLORS[obj.status].get("bg"),
                fc=obj.STATUS_COLORS[obj.status].get("fg"),
                o=obj.get_status_display())

        colored_status.allow_tags = True
# pylint: enable=R0201

        actions = [mbd_action_check, mbd_action_activate, mbd_action_deactivate, mbd_action_prepare, mbd_action_unprepare]
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
        return "{s}, last check {c}".format(s=self.get_status_display(), c=self.last_checked)

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
