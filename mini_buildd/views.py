# -*- coding: utf-8 -*-
import tempfile, logging

import django.core.management, django.http

log = logging.getLogger(__name__)

def example_view(request):
    return django.http.HttpResponse("example view function", mimetype="text/plain")
