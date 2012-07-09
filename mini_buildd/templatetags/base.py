# -*- coding: utf-8 -*-
import django

import mini_buildd

register = django.template.Library()


@register.simple_tag
def mbd_version():
    return mini_buildd.__version__
