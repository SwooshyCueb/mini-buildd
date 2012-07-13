# -*- coding: utf-8 -*-
import django.views.static
import django.views.generic
import django.views.generic.list_detail
import django.conf.urls.defaults

import mini_buildd.views
import mini_buildd.models

info_dict = {
    'queryset': mini_buildd.models.Repository.objects.all(),
}

urlpatterns = django.conf.urls.defaults.patterns(
    '',
    (r"^$", django.views.generic.simple.direct_to_template, {'template': 'mini_buildd/index.html'}),
    (r"^download/archive.key$", mini_buildd.views.get_archive_key),
    (r"^download/dput.cf$", mini_buildd.views.get_dput_conf),
    (r"^repositories/$", mini_buildd.views.get_repository_results),
    (r"^repositories/(?P<object_id>.+)/$", django.views.generic.list_detail.object_detail, info_dict),
)
