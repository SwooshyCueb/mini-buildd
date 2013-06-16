# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import django.conf.urls.defaults
import django.views.generic.base
import django.contrib.admin

django.contrib.admin.autodiscover()

# pylint: disable=E1120
urlpatterns = django.conf.urls.defaults.patterns(
    "",
    # mini_buildd
    (r"^$", django.views.generic.base.RedirectView.as_view(url="/mini_buildd/", permanent=False)),
    (r"^mini_buildd/", django.conf.urls.defaults.include("mini_buildd.urls")),
    # admin
    (r"^admin/doc/", django.conf.urls.defaults.include("django.contrib.admindocs.urls")),
    (r"^admin/", django.conf.urls.defaults.include(django.contrib.admin.site.urls)),
    # registration
    (r'^accounts/', django.conf.urls.defaults.include("registration.backends.default.urls")),)
# pylint: enable=E1120
