# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os

import django
import mini_buildd


register = django.template.Library()


@register.filter
def mbd_dict_get(dict_, key):
    return dict_.get(key)


@register.filter
def mbd_dirname(path):
    return os.path.dirname(path)


@register.simple_tag
def mbd_version():
    return mini_buildd.__version__


@register.filter
def mbd_daemon_is_running(dummy):
    return mini_buildd.daemon.get().is_running()


@register.simple_tag
def mbd_model_count(model):
    def count_str(count):
        if count:
            return "&nbsp;{d}&nbsp;".format(d=count)
        return ""

    try:
        # pylint: disable=W0123
        model_class = eval("mini_buildd.models.{m}".format(m=model))
        is_status_model = getattr(model_class, "mbd_is_prepared", None)
        total = model_class.objects.all().count()
        if is_status_model:
            active = model_class.objects.filter(status__exact=model_class.STATUS_ACTIVE).count()
            prepared = model_class.objects.filter(status__exact=model_class.STATUS_PREPARED).count()
            removed = model_class.objects.filter(status__exact=model_class.STATUS_REMOVED).count()

            return """\
<span title="Active instances"   style="background-color: green; color: white;">{active}</span>\
<span title="Prepared instances" style="background-color: yellow; color: black;">{prepared}</span>\
<span title="Removed instances" style="background-color: red; color: black;">{removed}</span>\
""".format(active=count_str(active),
           prepared=count_str(prepared),
           removed=count_str(removed))
        else:
            return """<span title="Total instances" style="color: black;">{total}</span>""".format(total=count_str(total))
    except:
        return "no model count"


def _mbd_e2n(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except:
        return None


def _mbd_distribution_options(repository, value_prefix="", **suiteoption_filter):
    result = ""
    for d in repository.mbd_distribution_strings(**suiteoption_filter):
        result += '<option value="{p}{d}">{d}</option>'.format(p=value_prefix, d=d)
    return result


@register.simple_tag
def mbd_distribution_options(repository, value_prefix="", **suiteoption_filter):
    "Generate 'option' HTML tags for 'select' form input for distribution strings."
    return _mbd_e2n(_mbd_distribution_options, repository, value_prefix=value_prefix, **suiteoption_filter)


@register.simple_tag
def mbd_distribution_apt_line(distribution, repository, suite_option):
    return _mbd_e2n(distribution.mbd_get_apt_line, repository, suite_option)


@register.simple_tag
def mbd_distribution_apt_sources_list(distribution, repository, suite_option):
    return _mbd_e2n(distribution.mbd_get_apt_sources_list, repository, suite_option)


@register.simple_tag
def mbd_distribution_apt_preferences(distribution, repository, suite_option):
    return _mbd_e2n(distribution.mbd_get_apt_preferences, repository, suite_option)


@register.simple_tag
def mbd_repository_desc(repository, distribution, suite_option):
    return _mbd_e2n(repository.mbd_get_description, distribution, suite_option)


@register.simple_tag
def mbd_repository_mandatory_version(repository, dist, suite):
    return _mbd_e2n(repository.layout.mbd_get_mandatory_version_regex, repository, dist, suite)
