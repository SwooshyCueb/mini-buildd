# -*- coding: utf-8 -*-
import logging

import django.http

from django.shortcuts import render_to_response

import mini_buildd.daemon

log = logging.getLogger(__name__)


def get_archive_key(request):
    return django.http.HttpResponse(mini_buildd.daemon.get().model.mbd_get_pub_key(), mimetype="text/plain")


def get_dput_conf(request):
    return django.http.HttpResponse(mini_buildd.daemon.get().model.mbd_get_dput_conf(), mimetype="text/plain")


def get_repository_results(request):
    ret = {}
    if request.GET:
        package = request.GET.get("package", None)
        dist = request.GET.get("dist", None)

        # DUMMY SEARCH: to be replaced later on!
        dict = tmp_dummy_package_search(package, dist)

        ret = render_to_response("mini_buildd/package_search_results.html", {'dict': dict})
    else:
        ret = render_to_response("mini_buildd/repository_list.html")

    return ret


# DUMMY SEARCH: to be removed later on!
# => search for "mbd-test-cpp", "testibus" or "*"!
def tmp_dummy_package_search(package, dist):
    dict = {}
    if ((package == "mbd-test-cpp" or package == "*") and (dist == "sid-test-experimental" or not dist)):
        dict['mbd-test-cpp_0.1.2~testSID+0'] = {}
        dict['mbd-test-cpp_0.1.2~testSID+0']['name'] = "mbd-test-cpp"
        dict['mbd-test-cpp_0.1.2~testSID+0']['version'] = "0.1.2"
        dict['mbd-test-cpp_0.1.2~testSID+0']['maintainer'] = "Stephan Sürken"
        dict['mbd-test-cpp_0.1.2~testSID+0']['maint_email'] = "absurd@debian.org"
        dict['mbd-test-cpp_0.1.2~testSID+0']['arch'] = "any"
        dict['mbd-test-cpp_0.1.2~testSID+0']['repository'] = "test"
        dict['mbd-test-cpp_0.1.2~testSID+0']['dist'] = "sid-test-experimental"

    if ((package == "mbd-test-cpp" or package == "*") and (dist == "sid-test-unstable" or not dist)):
        dict['mbd-test-cpp_0.1.0~testSID+3'] = {}
        dict['mbd-test-cpp_0.1.0~testSID+3']['name'] = "mbd-test-cpp"
        dict['mbd-test-cpp_0.1.0~testSID+3']['version'] = "0.1.0"
        dict['mbd-test-cpp_0.1.0~testSID+3']['maintainer'] = "Stephan Sürken"
        dict['mbd-test-cpp_0.1.0~testSID+3']['maint_email'] = "absurd@debian.org"
        dict['mbd-test-cpp_0.1.0~testSID+3']['arch'] = "any"
        dict['mbd-test-cpp_0.1.0~testSID+3']['repository'] = "test"
        dict['mbd-test-cpp_0.1.0~testSID+3']['dist'] = "sid-test-unstable"

    if ((package == "testibus" or package == "*") and (dist == "sid-test-stable" or not dist)):
        dict['testibus_1.0.0~testSID+8'] = {}
        dict['testibus_1.0.0~testSID+8']['name'] = "testibus"
        dict['testibus_1.0.0~testSID+8']['version'] = "1.0.0"
        dict['testibus_1.0.0~testSID+8']['maintainer'] = "Gerhard A. Dittes"
        dict['testibus_1.0.0~testSID+8']['maint_email'] = "Gerhard.Dittes@1und1.de"
        dict['testibus_1.0.0~testSID+8']['arch'] = "any"
        dict['testibus_1.0.0~testSID+8']['repository'] = "test"
        dict['testibus_1.0.0~testSID+8']['dist'] = "sid-test-stable"

    return dict
