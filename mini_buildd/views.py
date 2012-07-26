## -*- coding: utf-8 -*-
import django.http

import django.shortcuts

import mini_buildd.daemon

import mini_buildd.models.repository
import mini_buildd.models.chroot
import mini_buildd.models.gnupg


def show_index(_request):
    return django.shortcuts.render_to_response("mini_buildd/index.html",
                                               {"repositories": mini_buildd.models.repository.Repository.objects.all(),
                                                "chroots": mini_buildd.models.chroot.Chroot.objects.all(),
                                                "remotes": mini_buildd.models.gnupg.Remote.objects.all()})


def get_archive_key(_request):
    return django.http.HttpResponse(mini_buildd.daemon.get().model.mbd_get_pub_key(), mimetype="text/plain")


def get_dput_conf(_request):
    return django.http.HttpResponse(mini_buildd.daemon.get().model.mbd_get_dput_conf(), mimetype="text/plain")


def get_builder_state(_request):
    return django.http.HttpResponse(mini_buildd.daemon.get().get_builder_state().dump(), mimetype="text/plain")


def get_repository_results(request):
    if request.GET:
        authenticated = (request.user.is_authenticated() and request.user.is_superuser)
        action = request.GET.get("action", None)

        if action == "search":
            package = request.GET.get("package", None)
            repository = request.GET.get("repository", None)
            codename = request.GET.get("codename", None)

            if repository:
                search_repos = [mini_buildd.models.repository.Repository.mbd_get_prepared().get(identity=repository)]
            else:
                search_repos = mini_buildd.models.repository.Repository.mbd_get_prepared()

            result = {}
            for r in search_repos:
                result[r.identity] = r.mbd_package_search(package, codename)

            ret = django.shortcuts.render_to_response("mini_buildd/package_search_results.html",
                                                      {'authenticated': authenticated, 'result': result})
        elif action == "propagate":
            result = {}
            if authenticated:
                package = request.GET.get("package", None)
                version = request.GET.get("version", None)
                repository = request.GET.get("repository", None)
                from_distribution = request.GET.get("from_distribution", None)
                to_distribution = request.GET.get("to_distribution", None)

                r = mini_buildd.models.repository.Repository.objects.get(identity=repository)
                result = r.mbd_reprepro().copysrc(to_distribution, from_distribution, package, version)

            ret = django.shortcuts.render_to_response("mini_buildd/package_propagation_results.html",
                                                      {'authenticated': authenticated, 'result': result})

        elif action == "remove":
            result = {}
            if authenticated:
                package = request.GET.get("package", None)
                version = request.GET.get("version", None)
                repository = request.GET.get("repository", None)
                distribution = request.GET.get("distribution", None)

                r = mini_buildd.models.repository.Repository.objects.get(identity=repository)
                result = r.mbd_reprepro().removesrc(distribution, package, version)

            ret = django.shortcuts.render_to_response("mini_buildd/package_propagation_results.html",
                                                      {'authenticated': authenticated, 'result': result})

    else:
        ret = ""

    return ret
