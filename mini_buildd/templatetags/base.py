# -*- coding: utf-8 -*-
import django
import mini_buildd


register = django.template.Library()


@register.simple_tag
def mbd_version():
    return mini_buildd.__version__


@register.simple_tag(takes_context=True)
def admin_check_daemon_running(context):
    context['daemon_running'] = False
    if mini_buildd.daemon.get().is_running():
        context['daemon_running'] = True
    return ""


@register.simple_tag
def repository_dist(repository, dist, suite):
    return repository.mbd_get_dist(dist, suite)


@register.simple_tag
def repository_desc(repository, dist, suite):
    return repository.mbd_get_desc(dist, suite)


@register.simple_tag
def repository_apt_line(repository, dist, suite):
    return repository.mbd_get_apt_line(dist, suite)


@register.simple_tag
def repository_sources(repository, dist, suite):
    return repository.mbd_get_sources(dist, suite)


@register.simple_tag
def repository_mandatory_version(repository, dist, suite):
    return repository.layout.mbd_get_mandatory_version_regex(repository, dist, suite)
