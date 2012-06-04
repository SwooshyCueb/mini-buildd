from django import template

import mini_buildd

register = template.Library()

@register.simple_tag
def mbd_version():
    return mini_buildd.__version__
