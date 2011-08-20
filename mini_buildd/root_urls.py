from django.conf.urls.defaults import patterns, include, url
from django.views.generic.simple import redirect_to
from django.contrib import admin
import mini_buildd.urls

admin.autodiscover()

urlpatterns = patterns('',
                       # mini_buildd
                       (r'^$', redirect_to, {'url': '/mini_buildd/', 'permanent': False}),
                       (r'^mini_buildd/', include('mini_buildd.urls')),
                       # admin
                       url(r'^admin/doc/', include('django.contrib.admindocs.urls')),
                       url(r'^admin/', include(admin.site.urls)),
                       # @todo: workaround to get static admin data on Debian, at least
                       (r'^static/admin/(?P<path>.*)$', 'django.views.static.serve', {'document_root': '/usr/share/pyshared/django/contrib/admin/media/'})
)
