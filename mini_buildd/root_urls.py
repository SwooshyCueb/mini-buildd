# -*- coding: utf-8 -*-
from __future__ import unicode_literals

# pylint: disable=F0401,E0611
try:
    # django >= 1.6
    from django.conf.urls import patterns, include
except ImportError:
    # django 1.5
    from django.conf.urls.defaults import patterns, include
# pylint: enable=F0401,E0611

import django.views.generic.base
import django.contrib.admin

django.contrib.admin.autodiscover()

# pylint: disable=E1120
urlpatterns = patterns(
    "",
    # mini_buildd
    (r"^$", django.views.generic.base.RedirectView.as_view(url="/mini_buildd/", permanent=False)),
    (r"^mini_buildd/", include("mini_buildd.urls")),
    # admin
    (r"^admin/doc/", include("django.contrib.admindocs.urls")),
    (r"^admin/", include(django.contrib.admin.site.urls)),
    # registration
    (r'^accounts/', include("registration.backends.default.urls")),)
# pylint: enable=E1120
