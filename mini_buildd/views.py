# -*- coding: utf-8 -*-
import tempfile

import django.core.management
import django.http

import mini_buildd

def graph_models(request):
    with tempfile.NamedTemporaryFile(suffix=".png") as img:
        mini_buildd.log.info("Generating graphical model view using tmpfile=" + img.name)
        django.core.management.call_command('graph_models', 'mini_buildd', outputfile=img.name)
        return django.http.HttpResponse(img.read(), mimetype="image/png")
