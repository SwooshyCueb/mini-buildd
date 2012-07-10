# -*- coding: utf-8 -*-
import django

import mini_buildd.daemon
import mini_buildd.models

register = django.template.Library()


@register.simple_tag
def mbd_status():
    return mini_buildd.daemon.get().status_as_html()


@register.simple_tag
def mbd_repository_list():
    ret = ""
    if mini_buildd.models.Repository.objects.all().count() > 0:
        ret += "<ul>"
        for repo in mini_buildd.models.Repository.objects.all():
            ret += '<li><a href="repositories/' + repo.identity + '">' + repo.identity + '</a></li>'
        ret += "</ul>"
    else:
        ret += "<p>No repositories configured.</p>"

    return ret
