# -*- coding: utf-8 -*-
import tempfile

#from django.shortcuts import get_object_or_404, render_to_response
from django.core.management import call_command
import django.http

from mini_buildd import models
import mini_buildd

def graph_models(request):
    with tempfile.NamedTemporaryFile(suffix=".png") as img_file:
        mini_buildd.log.info("Generating graphical model view using tmpfile=" + img_file.name)
        call_command('graph_models', 'mini_buildd', outputfile=img_file.name)
        return django.http.HttpResponse(img_file.read(), mimetype="image/png")
