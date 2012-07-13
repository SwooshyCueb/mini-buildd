# -*- coding: utf-8 -*-
import django
import mini_buildd.models

register = django.template.Library()


@register.simple_tag
def repository_list_all():
    ret = ""
    if mini_buildd.models.Repository.objects.all().count() > 0:
        ret += "<ul>"
        for repo in mini_buildd.models.Repository.objects.all():
            ret += '<li><a href="/mini_buildd/repositories/' + repo.identity + '">' + repo.identity + '</a></li>'
        ret += "</ul>"
    else:
        ret += "<p>No repositories configured.</p>"

    return ret


@register.simple_tag
def get_package_search_results(dict):
    ret = ''
    if dict:
        ret += '<table>'
        ret += '  <tr>'
        ret += '    <th>Name</th>'
        ret += '    <th>Version</th>'
        ret += '    <th>Maintainer</th>'
        ret += '    <th>Architecture</th>'
        ret += '    <th>Repository</th>'
        ret += '    <th>Distribution</th>'
        ret += '  </tr>'

        for id in dict.keys():
            ret += '  <tr>'
            ret += '    <td>' + dict[id]['name'] + '</td>'
            ret += '    <td>' + dict[id]['version'] + '</td>'
            ret += '    <td><a href="mailto:' + dict[id]['maint_email'] + '">' + dict[id]['maintainer'] + '</a></td>'
            ret += '    <td>' + dict[id]['arch'] + '</td>'
            ret += '    <td><a href="/mini_buildd/repositories/' + dict[id]['repository'] + '/">' + dict[id]['repository'] + '</a></td>'
            ret += '    <td>' + dict[id]['dist'] + '</td>'
            ret += '  </tr>'

        ret += '</table>'
    else:
        ret += '<ul>'
        ret += '  <li><span class="alert">No packages found!</span></li>'
        ret += '  <li>Back to <a href="javascript: history.back()">search</a>.</li>'
        ret += '</ul>'

    return ret


@register.simple_tag
def repository_dist(repository, dist, suite):
    return repository.mbd_get_dist(dist, suite)


@register.simple_tag
def repository_origin(repository):
    return repository.mbd_get_origin()


@register.simple_tag
def repository_components(repository):
    return repository.mbd_get_components()


@register.simple_tag
def repository_architectures(repository, sep=u","):
    return sep.join(repository.mbd_get_architectures())


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
    return repository.mbd_get_mandatory_version(dist, suite)
