# -*- coding: utf-8 -*-
import logging

import django.http

from mini_buildd import daemon

log = logging.getLogger(__name__)

def get_archive_key(request):
    return django.http.HttpResponse(daemon.get().mbd_get_pub_key(), mimetype="text/plain")

def get_dput_conf(request):
    return django.http.HttpResponse(daemon.get().mbd_get_dput_conf(), mimetype="text/plain")
