import django.views.static, django.views.generic, django.views.generic.list_detail, django.conf.urls.defaults

from mini_buildd import views, models

info_dict = {
    'queryset': models.Repository.objects.all(),
}

urlpatterns = django.conf.urls.defaults.patterns(
    '',
    (r"^$", django.views.generic.simple.direct_to_template, {'template': 'mini_buildd/index.html'}),
    (r"^download/archive.key$", views.get_archive_key),
    (r"^download/dput.cf$", views.get_dput_conf),
    (r"^repositories/$", django.views.generic.list_detail.object_list, info_dict),
    (r"^repositories/(?P<object_id>.+)/$", django.views.generic.list_detail.object_detail, info_dict),
)
