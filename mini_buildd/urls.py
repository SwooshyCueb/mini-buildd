from django.conf.urls.defaults import *
from django.views.generic.simple import redirect_to
import django.views.generic

import mini_buildd.views

from mini_buildd.models import Repository
info_dict = {
    'queryset': Repository.objects.all(),
}

urlpatterns = patterns('',
                       (r"^$", django.views.generic.simple.redirect_to, {'url': "repositories/", 'permanent': False}),
                       (r"^repositories/$", 'django.views.generic.list_detail.object_list', info_dict),
                       (r"^repositories/(?P<object_id>.+)/$", 'django.views.generic.list_detail.object_detail', info_dict),
                       (r"^graph_models/$", 'mini_buildd.views.graph_models')

                       # @todo: django.views.static.serve should not be used for production
                       # Compat: Browse olde-style public_html/
                       #(r"^public_html/(?P<path>.*)$", 'django.views.static.serve', {'document_root': args.home + "/public_html/", 'show_indexes': True})
)
