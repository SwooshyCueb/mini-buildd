from django.conf.urls.defaults import *
#from django.views.generic.simple import redirect_to

import django.views.static, django.views.generic, django.views.generic.list_detail

from mini_buildd import setup, views, models

info_dict = {
    'queryset': models.Repository.objects.all(),
}

urlpatterns = patterns('',
                       (r"^$", django.views.generic.simple.redirect_to, {'url': "repositories/", 'permanent': False}),
                       (r"^download/archive.key$", views.get_archive_key),
                       (r"^download/dput.cf$", views.get_dput_conf),
                       (r"^repositories/$", django.views.generic.list_detail.object_list, info_dict),
                       (r"^repositories/(?P<object_id>.+)/$", django.views.generic.list_detail.object_detail, info_dict),
)
