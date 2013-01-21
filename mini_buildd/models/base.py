# -*- coding: utf-8 -*-
r"""
Generic module for models of the django app *mini_buildd*.

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
import re
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
        @classmethod
        def _mbd_save_or_delete_model(cls, request, obj, needs_restart, func):
            "Save/delete triggers: Automatically trigger Daemon restart on object change."
            if needs_restart:
                obj.mbd_msg_warn(request, "Auto-restarting daemon (consider temporary deactivation for extensive maintenance)")
                mini_buildd.misc.dont_care_run(obj.mbd_get_daemon().stop, request=request)
            func()
            if needs_restart:
                mini_buildd.misc.dont_care_run(obj.mbd_get_daemon().start, request=request)

        def save_model(self, request, obj, form, change):
            self._mbd_save_or_delete_model(request,
                                           obj,
                                           needs_restart=obj.mbd_get_daemon().is_running() and change and form.changed_data,
                                           func=obj.save)

        def delete_model(self, request, obj):
            def unprepare_and_delete():
                is_prepared_func = getattr(obj, "mbd_is_prepared", None)
                if is_prepared_func and is_prepared_func():
                    self.mbd_unprepare(request, obj)
                obj.delete()

            self._mbd_save_or_delete_model(request,
                                           obj,
                                           needs_restart=obj.mbd_get_daemon().is_running(),
                                           func=unprepare_and_delete)

    def __unicode__(self):
        return "{C}: {u}".format(C=self.__class__.__name__, u=self.mbd_unicode())

    def mbd_unicode(self):
        return "ERR: mbd_unicode() not impl. in {C}".format(C=self.__class__.__name__)

    @classmethod
    def _mbd_msg_d2p(cls, level):
        return {django.contrib.messages.DEBUG: logging.DEBUG,
                django.contrib.messages.INFO: logging.INFO,
                django.contrib.messages.SUCCESS: logging.INFO,
                django.contrib.messages.WARNING: logging.WARN,
                django.contrib.messages.ERROR: logging.ERROR}[level]

    @classmethod
    def mbd_msg(cls, level, request, msg):
        if request:
            django.contrib.messages.add_message(request, level, msg)
        LOG.log(cls._mbd_msg_d2p(level), msg)

    @classmethod
    def mbd_msg_debug(cls, request, msg):
        cls.mbd_msg(django.contrib.messages.DEBUG, request, msg)

    @classmethod
    def mbd_msg_info(cls, request, msg):
        cls.mbd_msg(django.contrib.messages.INFO, request, msg)

    @classmethod
    def mbd_msg_success(cls, request, msg):
        cls.mbd_msg(django.contrib.messages.SUCCESS, request, msg)

    @classmethod
    def mbd_msg_warn(cls, request, msg):
        cls.mbd_msg(django.contrib.messages.WARNING, request, msg)

    @classmethod
    def mbd_msg_error(cls, request, msg):
        cls.mbd_msg(django.contrib.messages.ERROR, request, msg)

    @classmethod
    def mbd_msg_exception(cls, request, msg, exception, level=django.contrib.messages.ERROR):
        if request:
            django.contrib.messages.add_message(request, level, "{m}: {e}".format(m=msg, e=exception))
        mini_buildd.setup.log_exception(LOG, msg, exception, level=cls._mbd_msg_d2p(level))

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

    @classmethod
    def mbd_validate_regex(cls, regex, value, field_name):
        if not re.match(regex, value):
            raise django.core.exceptions.ValidationError("{n} field does not match regex {r}".format(n=field_name, r=regex))


class StatusModel(Model):
    """
    Abstract model class for all models that carry a status. See Manual: :ref:`admin_configuration`.
    """
    # The main statuses: unprepared, prepared, active
    STATUS_UNPREPARED = 0
    STATUS_PREPARED = 1
    STATUS_ACTIVE = 2
    STATUS_CHOICES = (
        (STATUS_UNPREPARED, "Unprepared"),
        (STATUS_PREPARED, "Prepared"),
        (STATUS_ACTIVE, "Active"))
    STATUS_COLORS = {
        STATUS_UNPREPARED: {"bg": "yellow", "fg": "black"},
        STATUS_PREPARED: {"bg": "blue", "fg": "white"},
        STATUS_ACTIVE: {"bg": "green", "fg": "white"}}
    status = django.db.models.IntegerField(choices=STATUS_CHOICES, default=STATUS_UNPREPARED, editable=False)

    # Statuses of the prepared data, relevant for status "Prepared" only.
    # For "Unprepared" it's always NONE, for "Active" it's always the stamp of the last check.
    CHECK_NONE = datetime.datetime(datetime.MINYEAR, 1, 1, tzinfo=None)
    CHECK_CHANGED = datetime.datetime(datetime.MINYEAR, 1, 2, tzinfo=None)
    CHECK_FAILED = datetime.datetime(datetime.MINYEAR, 1, 3, tzinfo=None)
    CHECK_FAILED_REACTIVATE = datetime.datetime(datetime.MINYEAR, 1, 4, tzinfo=None)
    _CHECK_MAX = CHECK_FAILED_REACTIVATE
    CHECK_STRINGS = {
        CHECK_NONE: {"char": "-", "string": "Unchecked"},
        CHECK_CHANGED: {"char": "*", "string": "Model changed"},
        CHECK_FAILED: {"char": "x", "string": "Failed"},
        CHECK_FAILED_REACTIVATE: {"char": "A", "string": "Failed; Auto-activate when check succeeds (again))"}}
    last_checked = django.db.models.DateTimeField(default=CHECK_NONE, editable=False)

    # Obsoleted by CHECK_FAILED_REACTIVATE prepared data state
    auto_reactivate = django.db.models.BooleanField(default=False, editable=False)

    class Meta(Model.Meta):
        abstract = True

    class Admin(Model.Admin):
# pylint: disable=E1002
        def save_model(self, request, obj, form, change):
            if change and form.changed_data:
                if obj.mbd_is_active():
                    obj.status = obj.STATUS_PREPARED
                    obj.mbd_msg_warn(request, "{o}: Deactivated due to changes. Prepare data again.".format(o=obj))
                obj.last_checked = obj.CHECK_CHANGED
                obj.mbd_msg_warn(request, "{o}: Marked as changed.".format(o=obj))
            super(StatusModel.Admin, self).save_model(request, obj, form, change)
# pylint: enable=E1002

        @classmethod
        def _mbd_run_dependencies(cls, request, obj, func, **kwargs):
            for o in obj.mbd_get_mandatory_dependencies():
                func(request, o, **kwargs)
            for o in obj.mbd_get_optional_dependencies():
                try:
                    func(request, o, **kwargs)
                except:
                    obj.mbd_msg_warn(request, "{o}: Failed, but optional. Ignoring...".format(o=o))

        @classmethod
        def mbd_prepare(cls, request, obj):
            if not obj.mbd_is_prepared():
                # Fresh prepare
                cls._mbd_run_dependencies(request, obj, cls.mbd_prepare)
                obj.mbd_prepare(request)
                obj.status, obj.last_checked = obj.STATUS_PREPARED, obj.CHECK_NONE
                obj.save()
                obj.mbd_msg_info(request, "{o}: Prepare successful.".format(o=obj))
            elif obj.mbd_is_changed():
                # Update data on change
                obj.mbd_sync(request)
                obj.status, obj.last_checked = obj.STATUS_PREPARED, obj.CHECK_NONE
                obj.save()
                obj.mbd_msg_info(request, "{o}: Prepared data updated.".format(o=obj))
            else:
                obj.mbd_msg_info(request, "{o}: Already prepared.".format(o=obj))

        @classmethod
        def mbd_check(cls, request, obj, force=False, needs_activation=False):
            if obj.mbd_is_prepared() and not obj.mbd_is_changed():
                try:
                    # Also run for all status dependencies
                    cls._mbd_run_dependencies(request, obj, cls.mbd_check,
                                              force=force,
                                              needs_activation=obj.mbd_is_active() or obj.last_checked == obj.CHECK_FAILED_REACTIVATE)

                    if force or not obj.mbd_is_checked():
                        obj.mbd_check(request)
                        if obj.last_checked == obj.CHECK_FAILED_REACTIVATE:
                            obj.status = StatusModel.STATUS_ACTIVE
                            obj.mbd_msg_info(request, "{o}: Auto-reactivated.".format(o=obj))
                        obj.last_checked = datetime.datetime.now()

                        obj.save()
                        obj.mbd_msg_info(request, "{o}: Check successful.".format(o=obj))
                    else:
                        obj.mbd_msg_info(request, "{o}: Needs no check.".format(o=obj))

                    if needs_activation and not obj.mbd_is_active():
                        raise Exception("{o}: Not active, but a (tobe-)active item depends on it. Activate this first.".format(o=obj))
                except:
                    # Check failed, auto-deactivate and re-raise exception
                    obj.last_checked = max(obj.last_checked, obj.CHECK_FAILED)
                    if obj.mbd_is_active():
                        obj.status, obj.last_checked = obj.STATUS_PREPARED, obj.CHECK_FAILED_REACTIVATE
                        obj.mbd_msg_error(request, "{o}: Automatically deactivated.".format(o=obj))
                    obj.save()
                    raise
            else:
                raise Exception("{o}: Can't check unprepared or changed object.".format(o=obj))

        @classmethod
        def mbd_activate(cls, request, obj):
            if obj.mbd_is_prepared() and obj.mbd_is_checked():
                cls._mbd_run_dependencies(request, obj, cls.mbd_activate)
                obj.mbd_activate(request)
                obj.status = obj.STATUS_ACTIVE
                obj.save()
                obj.mbd_msg_info(request, "{o}: Activate successful.".format(o=obj))
            elif obj.mbd_is_prepared() and obj.last_checked == obj.CHECK_FAILED:
                obj.last_checked = obj.CHECK_FAILED_REACTIVATE
                obj.save()
                obj.mbd_msg_info(request, "{o}: Set to auto-activate when check succeeds.".format(o=obj))
            elif obj.mbd_is_active():
                obj.mbd_msg_info(request, "{o}: Already active.".format(o=obj))
            else:
                obj.mbd_msg_warn(request, "{o}: Must be prepared and checked to activate.".format(o=obj))

        @classmethod
        def mbd_deactivate(cls, request, obj):
            if obj.mbd_is_active():
                obj.mbd_deactivate(request)
            obj.status = min(obj.STATUS_PREPARED, obj.status)
            if obj.last_checked == obj.CHECK_FAILED_REACTIVATE:
                obj.last_checked = obj.CHECK_FAILED
            obj.save()
            obj.mbd_msg_info(request, "{o}: Deactivate successful.".format(o=obj))

        @classmethod
        def mbd_unprepare(cls, request, obj):
            if obj.mbd_is_prepared():
                obj.mbd_unprepare(request)
                obj.status, obj.last_checked = obj.STATUS_UNPREPARED, obj.CHECK_NONE
                obj.save()
                obj.mbd_msg_info(request, "{o}: Unprepare successful.".format(o=obj))
            else:
                obj.mbd_msg_info(request, "{o}: Already unprepared.".format(o=obj))

        @classmethod
        def mbd_action(cls, request, queryset, action, **kwargs):
            """
            Try to run action on each object in queryset, and
            emit error message on failure.
            """
            for o in queryset:
                try:
                    getattr(cls, "mbd_" + action)(request, o, **kwargs)
                except Exception as e:
                    o.mbd_msg_exception(request, "{o}: {a} failed".format(o=o, a=action), e)

        def mbd_action_prepare(self, request, queryset):
            self.mbd_action(request, queryset, "prepare")
        mbd_action_prepare.short_description = "Prepare"

        def mbd_action_check(self, request, queryset):
            self.mbd_action(request, queryset, "check", force=True)
        mbd_action_check.short_description = "Check"

        def mbd_action_activate(self, request, queryset):
            self.mbd_action(request, queryset, "activate")
        mbd_action_activate.short_description = "Activate"

        def mbd_action_deactivate(self, request, queryset):
            self.mbd_action(request, queryset, "deactivate")
        mbd_action_deactivate.short_description = "Deactivate"

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

# pylint: disable=R0201
        def colored_status(self, obj):
            return '<div style="background-color:{bc};color:{fc};padding:2px 0px 2px 5px" title="Last check: {t}">{o}</div>'.format(
                bc=obj.STATUS_COLORS[obj.status].get("bg"),
                fc=obj.STATUS_COLORS[obj.status].get("fg"),
                t=obj.CHECK_STRINGS.get(obj.last_checked, {}).get("string", obj.last_checked),
                o=obj.mbd_get_status_display())

        colored_status.allow_tags = True
# pylint: enable=R0201

        actions = [mbd_action_prepare, mbd_action_check, mbd_action_activate, mbd_action_deactivate, mbd_action_unprepare]
        list_display = ["colored_status", "__unicode__"]

    def __unicode__(self):
        return "{u} ({s})".format(u=super(StatusModel, self).__unicode__(), s=self.mbd_get_status_display())

    #
    # Action default hooks and helpers
    #
    def mbd_activate(self, request):
        "Per default, nothing is to be done on 'activate'."
        pass

    def mbd_deactivate(self, request):
        "Per default, nothing is to be done on 'deactivate'."
        pass

    def _mbd_sync_by_purge_and_create(self, request):
        mini_buildd.models.base.StatusModel.Admin.mbd_unprepare(request, self)
        mini_buildd.models.base.StatusModel.Admin.mbd_prepare(request, self)

    #
    # Status abstractions and helpers
    #
    def mbd_is_prepared(self):
        return self.status >= self.STATUS_PREPARED

    def mbd_is_active(self):
        return self.status >= self.STATUS_ACTIVE

    def mbd_is_checked(self):
        return self.last_checked > self._CHECK_MAX

    def mbd_is_changed(self):
        return self.last_checked == self.CHECK_CHANGED

    @classmethod
    def mbd_get_active(cls):
        return cls.objects.filter(status__gte=cls.STATUS_ACTIVE)

    @classmethod
    def mbd_get_active_or_auto_reactivate(cls):
        return cls.objects.filter(django.db.models.Q(status__gte=cls.STATUS_ACTIVE) |
                                  django.db.models.Q(last_checked=cls.CHECK_FAILED_REACTIVATE))

    @classmethod
    def mbd_get_prepared(cls):
        return cls.objects.filter(status__gte=cls.STATUS_PREPARED)

    def mbd_get_status_display(self):
        p = ""
        if self.status == self.STATUS_PREPARED and self.last_checked <= self._CHECK_MAX:
            p = " [{p}]".format(p=self.CHECK_STRINGS.get(self.last_checked, {}).get("char", self.last_checked))
        return "{s}{p}".format(s=self.get_status_display(), p=p)

    def mbd_get_mandatory_dependencies(self):
        LOG.debug("No mandatory dependencies for {s}".format(s=self))
        return []

    def mbd_get_optional_dependencies(self):
        LOG.debug("No optional dependencies for {s}".format(s=self))
        return []
