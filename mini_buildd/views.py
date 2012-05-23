# -*- coding: utf-8 -*-
import tempfile
import logging

import django.core.management
import django.http

log = logging.getLogger(__name__)

def graph_models(request):
    try:
        with tempfile.NamedTemporaryFile(suffix=".png") as img:
            log.info("Generating graphical model view using tmpfile=" + img.name)
            django.core.management.call_command('graph_models', 'mini_buildd', outputfile=img.name)
            return django.http.HttpResponse(img.read(), mimetype="image/png")
    except:
        return django.http.HttpResponse("Can't produce graphic (python-pygraphviz not installed?)", mimetype="text/plain")
