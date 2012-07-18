# -*- coding: utf-8 -*-
import logging

import django.http

from django.shortcuts import render_to_response

import mini_buildd.daemon

import mini_buildd.models


log = logging.getLogger(__name__)


def show_index(request):
    return render_to_response("mini_buildd/index.html",
                              {"repositories": mini_buildd.models.Repository.objects.all(),
                               "chroots": mini_buildd.models.Chroot.objects.all(),
                               "remotes": mini_buildd.models.Remote.objects.all()})


def get_archive_key(request):
    return django.http.HttpResponse(mini_buildd.daemon.get().model.mbd_get_pub_key(), mimetype="text/plain")


def get_dput_conf(request):
    return django.http.HttpResponse(mini_buildd.daemon.get().model.mbd_get_dput_conf(), mimetype="text/plain")


def get_builder_state(request):
    return django.http.HttpResponse(mini_buildd.daemon.get().get_builder_state().dump(), mimetype="text/plain")


def get_repository_results(request):
    if request.GET:
        authenticated = (request.user.is_authenticated() and request.user.is_superuser)
        action = request.GET.get("action", None)

        if action == "search":
            package = request.GET.get("package", None)
            dist = request.GET.get("dist", None)

            # DUMMY SEARCH: to be replaced later on!
            result = tmp_dummy_package_search(package, dist)

            ret = render_to_response("mini_buildd/package_search_results.html",
                                     {'authenticated': authenticated, 'result': result})
        elif action == "propagate":
            result = {}
            if authenticated:
                package = request.GET.get("package", None)
                version = request.GET.get("version", None)
                repository = request.GET.get("repository", None)
                from_dist = request.GET.get("from_dist", None)
                to_dist = request.GET.get("to_dist", None)

                # DUMMY PROPAGATION: to be replaced later on!
                result = tmp_dummy_propagate_package(package, version, repository, from_dist, to_dist)

            ret = render_to_response("mini_buildd/package_propagation_results.html",
                                     {'authenticated': authenticated, 'result': result})
    else:
        ret = render_to_response("mini_buildd/repository_list.html",
                                 {'repositories': mini_buildd.models.Repository.objects.all()})

    return ret


# DUMMY SEARCH: to be removed later on!
# => search for "mbd-test-cpp", "testibus" or "*"!
def tmp_dummy_package_search(package, dist):
    result = {}
    result["mbd-test-cpp"] = {}
    package_found = False

    if ((package == "mbd-test-cpp" or package == "*") and (dist == "sid-test-experimental" or not dist)):
        package_found = True
        result["mbd-test-cpp"]["0.1.2~testSID+0"] = []
        result["mbd-test-cpp"]["0.1.2~testSID+0"].append(("maintainer", "Stephan Sürken"))
        result["mbd-test-cpp"]["0.1.2~testSID+0"].append(("maintainer_email", "absurd@debian.org"))
        result["mbd-test-cpp"]["0.1.2~testSID+0"].append(("repository", "test"))
        result["mbd-test-cpp"]["0.1.2~testSID+0"].append(("dist", "sid-test-experimental"))

    if ((package == "mbd-test-cpp" or package == "*") and (dist == "sid-test-unstable" or not dist)):
        package_found = True
        result["mbd-test-cpp"]["0.1.2~testSID+3"] = []
        result["mbd-test-cpp"]["0.1.2~testSID+3"].append(("maintainer", "Stephan Sürken"))
        result["mbd-test-cpp"]["0.1.2~testSID+3"].append(("maintainer_email", "absurd@debian.org"))
        result["mbd-test-cpp"]["0.1.2~testSID+3"].append(("repository", "test"))
        result["mbd-test-cpp"]["0.1.2~testSID+3"].append(("dist", "sid-test-unstable"))
        result["mbd-test-cpp"]["0.1.2~testSID+3"].append(("can_propagate_to", "sid-test-testing"))

    if ((package == "testibus" or package == "*") and (dist == "sid-test-stable" or not dist)):
        package_found = True
        result["testibus"] = {}
        result["testibus"]["1.0.0~testSID+8"] = []
        result["testibus"]["1.0.0~testSID+8"].append(("maintainer", "Gerhard A. Dittes"))
        result["testibus"]["1.0.0~testSID+8"].append(("maintainer_email", "Gerhard.Dittes@1und1.de"))
        result["testibus"]["1.0.0~testSID+8"].append(("repository", "test"))
        result["testibus"]["1.0.0~testSID+8"].append(("dist", "sid-test-stable"))

    if not package_found:
        result = {}

    return result


# DUMMY PROPAGATION: to be removed later on!
# Todo: think about a useful "result-structure"
def tmp_dummy_propagate_package(package, version, repository, from_dist, to_dist):
    return "Repository " + repository + ": Successfully propagated " + package + " (" + version + ") from " + from_dist + " to " + to_dist + "."
