# -*- coding: utf-8 -*-
import django

from mini_buildd import __version__

register = django.template.Library()

@register.simple_tag
def mbd_version():
    return __version__
