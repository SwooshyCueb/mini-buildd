from django import template

from mini_buildd import __version__, daemon

register = template.Library()

@register.simple_tag
def mbd_version():
    return __version__
