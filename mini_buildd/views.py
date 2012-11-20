# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os.path
import glob
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
    # Note: Adding api_args.package if applicable; this will enable the "Show package" back link even on error pages.
    response = django.shortcuts.render(request,
                                       "mini_buildd/error.html",
                                       {"code": code,
                                        "meaning": meaning,
                                        "description": description,
                                        "api_args": {"package": request.GET.get("package", None)}},
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

        api_cmd = request.GET.get("command", None)
        if not api_cmd in mini_buildd.api.COMMANDS:
            return error400_bad_request(request, "API: Unknown command '{c}'".format(c=api_cmd))

        api_cls = mini_buildd.api.COMMANDS[api_cmd]

        authenticated = request.user.is_authenticated() and request.user.is_staff
        if api_cls.LOGIN and not authenticated:
            return error401_unauthorized(request, "API: '{c}': Needs staff user login".format(c=api_cmd))

        # Generate api_args and api_uri
        api_args = api_cls.filter_api_args(request.GET)
        api_uri = "{b}?command={c}&{a}".format(b=request.path, c=api_cmd, a=urllib.urlencode(api_args))

        output = request.GET.get("output", "html")

        # Check confirmable calls
        if api_cls.CONFIRM and request.GET.get("confirm", None) != api_cmd:
            if output != "html":
                return error401_unauthorized(request, "API: '{c}': Needs to be confirmed".format(c=api_cmd))
            else:
                return django.shortcuts.render_to_response("mini_buildd/api_confirm.html",
                                                           {"command": api_cmd,
                                                            "authenticated": authenticated,
                                                            "api_args": api_args,
                                                            "api_uri": api_uri})

        # Run API call. Runs actual code in constructor (with dep-injection via daemon object)
        result = api_cls(api_args, mini_buildd.daemon.get())

        # Generate API call output
        if output == "html":
            return django.shortcuts.render_to_response(["mini_buildd/api_{c}.html".format(c=api_cmd), "mini_buildd/api_default.html".format(c=api_cmd)],
                                                       {"command": api_cmd,
                                                        "authenticated": authenticated,
                                                        "result": result,
                                                        "api_args": api_args,
                                                        "api_uri": api_uri})
        elif output == "plain":
            return django.http.HttpResponse("{r}".format(r=result), mimetype="text/plain")
        elif output == "python":
            return django.http.HttpResponse(pickle.dumps(result), mimetype="application/python-pickle")
        else:
            return django.http.HttpResponseBadRequest("<h1>Unknow output type {o}</h1>".format(o=output))
    except Exception as e:
        mini_buildd.setup.log_exception(LOG, "API internal error", e)
        return error500_internal(request, "API: Internal error: {e}".format(e=e))
