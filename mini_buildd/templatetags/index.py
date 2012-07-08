from django import template

from mini_buildd import daemon, models

register = template.Library()

@register.simple_tag
def mbd_status():
    return daemon.get().status_as_html()

@register.simple_tag
def mbd_repository_list():
    ret = "<ul>"
    for repo in models.Repository.objects.all():
        ret += '<li><a href="repositories/' + repo.identity + '">' + repo.identity + '</a></li>'
    ret += "</ul>"
    return ret;
