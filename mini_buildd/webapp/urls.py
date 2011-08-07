from django.conf.urls.defaults import patterns, include, url
from django.contrib import admin

admin.autodiscover()

import mini_buildd.webapp.views

urlpatterns = patterns('',
                       (r'^$', 'mini_buildd.webapp.views.index'),
                       url(r'^admin/doc/', include('django.contrib.admindocs.urls')),
                       url(r'^admin/', include(admin.site.urls)),
                       (r'^static/admin/(?P<path>.*)$', 'django.views.static.serve', {'document_root': '/usr/share/pyshared/django/contrib/admin/media/'}),
                       (r'^rep/(?P<path>.*)$', 'django.views.static.serve', {'document_root': '/home/mini-buildd/rep/', 'show_indexes': True}),
#                       ('^admin-media/$', redirect_to, {'file': '/bar/%(id)s/'}),
)
