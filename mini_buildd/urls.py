# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import django.views.generic.detail
import django.conf.urls.defaults

import mini_buildd.views
import mini_buildd.models.repository

urlpatterns = django.conf.urls.defaults.patterns(
    '',
    (r"^$", mini_buildd.views.home),
    (r"^log/(.+)/(.+)/(.+)/$", mini_buildd.views.log),
    # pylint: disable=E1120
    (r"^repositories/(?P<pk>.+)/$", django.views.generic.detail.DetailView.as_view(model=mini_buildd.models.repository.Repository)),
    # pylint: enable=E1120
    (r"^api$", mini_buildd.views.api))

django.conf.urls.handler400 = mini_buildd.views.error400_bad_request
django.conf.urls.handler401 = mini_buildd.views.error401_unauthorized
django.conf.urls.handler404 = mini_buildd.views.error404_not_found
django.conf.urls.handler500 = mini_buildd.views.error500_internal
