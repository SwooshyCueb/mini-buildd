# -*- coding: utf-8 -*-
import django

import mini_buildd.daemon

register = django.template.Library()


@register.simple_tag
def mbd_status():
    return mini_buildd.daemon.get().status_as_html()
