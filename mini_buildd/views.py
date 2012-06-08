# -*- coding: utf-8 -*-
import tempfile, logging

import django.core.management, django.http

log = logging.getLogger(__name__)

def get_archive_key(request):
    log.info(request)
    from mini_buildd import daemon
    return django.http.HttpResponse(daemon.Daemon.objects.all()[0].gnupg.get_pub_key(), mimetype="text/plain")
