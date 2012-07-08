# -*- coding: utf-8 -*-
import logging

import django.http

import mini_buildd.daemon

log = logging.getLogger(__name__)

def get_archive_key(request):
    return django.http.HttpResponse(mini_buildd.daemon.get().model.mbd_get_pub_key(), mimetype="text/plain")

def get_dput_conf(request):
    return django.http.HttpResponse(mini_buildd.daemon.get().model.mbd_get_dput_conf(), mimetype="text/plain")
