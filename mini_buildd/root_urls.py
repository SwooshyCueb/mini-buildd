# -*- coding: utf-8 -*-
import django.conf.urls.defaults
import django.views.generic.simple
import django.contrib

import mini_buildd

django.contrib.admin.autodiscover()

urlpatterns = django.conf.urls.defaults.patterns(
    '',
    # mini_buildd
    (r"^$", django.views.generic.simple.redirect_to, {'url': "/mini_buildd/", 'permanent': False}),
    (r"^mini_buildd/", django.conf.urls.defaults.include('mini_buildd.urls')),
    # admin
    django.conf.urls.defaults.url(r"^admin/doc/", django.conf.urls.defaults.include('django.contrib.admindocs.urls')),
    django.conf.urls.defaults.url(r"^admin/", django.conf.urls.defaults.include(django.contrib.admin.site.urls)),
    # @todo: Workaround for  static admin data on Debian wheezy, django 1.3
    (r"^static/admin/(?P<path>.*)$", 'django.views.static.serve', {'document_root': "/usr/share/pyshared/django/contrib/admin/media/"}),
    # @todo: Workaround for  static admin data on Debian squeeze, django 1.2
    (r"^media/(?P<path>.*)$", 'django.views.static.serve', {'document_root': "/usr/share/pyshared/django/contrib/admin/media/"})
    )
