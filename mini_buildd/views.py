# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os.path
import glob
import copy
import pickle
import urllib
import logging

import django.core.exceptions
import django.http
import django.shortcuts
import django.template

import mini_buildd.daemon

import mini_buildd.models.repository
import mini_buildd.models.chroot
import mini_buildd.models.gnupg

LOG = logging.getLogger(__name__)


def error(request, code, meaning, description):
    response = django.shortcuts.render(request,
                                       "mini_buildd/error.html",
                                       {"code": code,
                                        "meaning": meaning,
                                        "description": description},
                                       status=code)
    response["X-Mini-Buildd-Error"] = description
    return response


def error400_bad_request(request, description="Bad request"):
    return error(request,
                 400,
                 "Bad Request",
                 description)


def error401_unauthorized(request, description="Missing authorization"):
    return error(request,
                 401,
                 "Unauthorized",
                 description)


def error404_not_found(request, description="The requested resource could not be found"):
    return error(request,
                 404,
                 "Not Found",
                 description)


def error500_internal(request, description="Sorry, something went wrong"):
    return error(request,
                 500,
                 "Internal Server Error",
                 description)


def home(_request):
    return django.shortcuts.render_to_response("mini_buildd/home.html",
                                               {"daemon": mini_buildd.daemon.get(),
                                                "repositories": mini_buildd.models.repository.Repository.mbd_get_prepared(),
                                                "chroots": mini_buildd.models.chroot.Chroot.mbd_get_prepared(),
                                                "remotes": mini_buildd.models.gnupg.Remote.mbd_get_prepared()})


def log(_request, repository, package, version):
    def get_logs(installed=True):
        result = {}
        path = os.path.join(mini_buildd.setup.LOG_DIR, repository, "" if installed else "_failed", package, version)
        for buildlog in glob.glob("{p}/*/*.buildlog".format(p=path)):
            # buildlog: "LOG_DIR/REPO/[_failed/]PACKAGE/VERSION/ARCH/PACKAGE_VERSION_ARCH.buildlog"
            arch = os.path.basename(os.path.dirname(buildlog))
            result[arch] = buildlog.replace(mini_buildd.setup.LOG_DIR, "")
        return result

    return django.shortcuts.render_to_response("mini_buildd/log.html",
                                               {"repository": repository,
                                                "package": package,
                                                "version": version,
                                                "logs": {"installed": get_logs(),
                                                         "failed": get_logs(installed=False)}})


def api(request):
    try:
        if request.method != 'GET':
            return error400_bad_request(request, "API: Allows GET requests only")

        command = request.GET.get("command", None)
        if not command in mini_buildd.api.COMMANDS:
            return error400_bad_request(request, "API: Unknown command '{c}'".format(c=command))

        authenticated = request.user.is_authenticated() and request.user.is_staff
        if mini_buildd.api.COMMANDS[command].LOGIN and not authenticated:
            return error401_unauthorized(request, "API: '{c}': Needs staff user login".format(c=command))

        # Generate standard python dict from GET parms
        args = {}
        for k, v in request.GET.iteritems():
            args[k] = v

        # Get API object. Runs actual code in constructor (with dep-injection via daemon object).
        result = mini_buildd.api.COMMANDS[command](args, mini_buildd.daemon.get())

        output = request.GET.get("output", "html")

        # Generate generic api call uris to put on html output pages
        api_call = {}
        for t in ["plain", "python"]:
            args = copy.copy(request.GET)
            args["output"] = t
            api_call[t] = "{b}?{a}".format(b=request.path, a=urllib.urlencode(args))

        if output == "html":
            return django.shortcuts.render_to_response(["mini_buildd/api_{c}.html".format(c=command), "mini_buildd/api_default.html".format(c=command)],
                                                       {"command": command,
                                                        "authenticated": authenticated,
                                                        "result": result,
                                                        "api_call": api_call})
        elif output == "plain":
            return django.http.HttpResponse("{r}".format(r=result), mimetype="text/plain")
        elif output == "python":
            return django.http.HttpResponse(pickle.dumps(result), mimetype="application/python-pickle")
        else:
            return django.http.HttpResponseBadRequest("<h1>Unknow output type {o}</h1>".format(o=output))
    except Exception as e:
        mini_buildd.setup.log_exception(LOG, "API internal error", e)
        return error500_internal(request, "API: Internal error: {e}".format(e=e))
