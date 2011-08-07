from django.shortcuts import render_to_response

from mini_buildd_shconf import *

def index(request):
    return render_to_response('index.html', { 'mbd_id': mbd_id })
