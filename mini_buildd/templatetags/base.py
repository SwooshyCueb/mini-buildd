# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import django
import mini_buildd


register = django.template.Library()


@register.simple_tag
def mbd_version():
    return mini_buildd.__version__


@register.simple_tag(takes_context=True)
def mbd_admin_check_daemon_running(context):
    context['daemon_running'] = False
    if mini_buildd.daemon.get().is_running():
        context['daemon_running'] = True
    return ""


@register.simple_tag
def mbd_distribution_apt_line(distribution, repository, suite_option):
    return distribution.mbd_get_apt_line(repository, suite_option)


@register.simple_tag
def mbd_distribution_apt_sources_list(distribution, repository, suite_option):
    return distribution.mbd_get_apt_sources_list(repository, suite_option)


@register.simple_tag
def mbd_distribution_apt_preferences(distribution, repository, suite_option):
    return distribution.mbd_get_apt_preferences(repository, suite_option)


@register.simple_tag
def mbd_repository_desc(repository, distribution, suite_option):
    return repository.mbd_get_description(distribution, suite_option)


@register.simple_tag
def mbd_repository_mandatory_version(repository, dist, suite):
    return repository.layout.mbd_get_mandatory_version_regex(repository, dist, suite)
