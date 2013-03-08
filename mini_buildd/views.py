# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os.path
import glob
import pickle
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


def error(request, code, meaning, description, api_cmd=None):
    # Note: Adding api_cmd if applicable; this will enable automated api links even on error pages.
    response = django.shortcuts.render(request,
                                       "mini_buildd/error.html",
                                       {"code": code,
                                        "meaning": meaning,
                                        "description": description,
                                        "api_cmd": api_cmd},
                                       status=code)
    response["X-Mini-Buildd-Error"] = description
    return response


def error400_bad_request(request, description="Bad request", api_cmd=None):
    return error(request,
                 400,
                 "Bad Request",
                 description,
                 api_cmd)


def error401_unauthorized(request, description="Missing authorization", api_cmd=None):
    return error(request,
                 401,
                 "Unauthorized",
                 description,
                 api_cmd)


def error404_not_found(request, description="The requested resource could not be found", api_cmd=None):
    return error(request,
                 404,
                 "Not Found",
                 description,
                 api_cmd)


def error405_method_not_allowed(request, description="The resource does not allow this request", api_cmd=None):
    return error(request,
                 405,
                 "Method Not Allowed",
                 description,
                 api_cmd)


def error500_internal(request, description="Sorry, something went wrong", api_cmd=None):
    return error(request,
                 500,
                 "Internal Server Error",
                 description,
                 api_cmd)


def home(request):
    return django.shortcuts.render_to_response("mini_buildd/home.html",
                                               {"daemon": mini_buildd.daemon.get(),
                                                "repositories": mini_buildd.models.repository.Repository.mbd_get_prepared(),
                                                "chroots": mini_buildd.models.chroot.Chroot.mbd_get_prepared(),
                                                "remotes": mini_buildd.models.gnupg.Remote.mbd_get_prepared()},
                                               django.template.RequestContext(request))


def log(request, repository, package, version):
    def get_logs(installed):
        path = os.path.join(mini_buildd.setup.LOG_DIR, repository, "" if installed else "_failed", package, version)

        buildlogs = {}
        for buildlog in glob.glob("{p}/*/*.buildlog".format(p=path)):
            # buildlog: "LOG_DIR/REPO/[_failed/]PACKAGE/VERSION/ARCH/PACKAGE_VERSION_ARCH.buildlog"
            arch = os.path.basename(os.path.dirname(buildlog))
            buildlogs[arch] = buildlog.replace(mini_buildd.setup.LOG_DIR, "")

        changes = None
        for c in glob.glob("{p}/*/*.changes".format(p=path)):
            # changes: "LOG_DIR/REPO/[_failed/]PACKAGE/VERSION/ARCH/PACKAGE_VERSION_ARCH.changes"
            if not ("mini-buildd-buildrequest" in c or "mini-buildd-buildresult" in c):
                with open(c) as f:
                    changes = f.read()
                break

        return {"changes": changes, "buildlogs": buildlogs}

    return django.shortcuts.render_to_response("mini_buildd/log.html",
                                               {"repository": repository,
                                                "package": package,
                                                "version": version,
                                                "logs": [("Installed", get_logs(installed=True)),
                                                         ("Failed", get_logs(installed=False))]},
                                               django.template.RequestContext(request))


def api(request):
    api_cmd = None
    try:
        if request.method != 'GET':
            return error400_bad_request(request, "API: Allows GET requests only")

        # Get API class from 'command' parameter
        command = request.GET.get("command", None)
        if not command in mini_buildd.api.COMMANDS:
            return error400_bad_request(request, "API: Unknown command '{c}'".format(c=command))
        api_cls = mini_buildd.api.COMMANDS[command]

        # Authentication
        if api_cls.LOGIN and not (request.user.is_authenticated() and request.user.is_staff):
            return error401_unauthorized(request, "API: '{c}': Needs staff user login".format(c=command))

        # Generate command object
        api_cmd = api_cls(request.GET, request)

        output = request.GET.get("output", "html")

        # Check confirmable calls
        if api_cls.CONFIRM and request.GET.get("confirm", None) != command:
            if output != "html":
                return error401_unauthorized(request, "API: '{c}': Needs to be confirmed".format(c=command))
            else:
                return django.shortcuts.render_to_response("mini_buildd/api_confirm.html",
                                                           {"api_cmd": api_cmd,
                                                            "referer": request.META.get("HTTP_REFERER")},
                                                           django.template.RequestContext(request))

        # Run API call (dep-injection via daemon object)
        api_cmd.run(mini_buildd.daemon.get())

        # Generate API call output
        response = None
        if output == "html":
            response = django.shortcuts.render_to_response(["mini_buildd/api_{c}.html".format(c=command),
                                                            "mini_buildd/api_default.html".format(c=command)],
                                                           {"api_cmd": api_cmd},
                                                           django.template.RequestContext(request))

        elif output == "plain":
            response = django.http.HttpResponse(api_cmd.__unicode__().encode("UTF-8"), mimetype="text/plain; charset=utf-8")

        elif output == "python":
            response = django.http.HttpResponse(pickle.dumps(api_cmd, pickle.HIGHEST_PROTOCOL),
                                                mimetype="application/python-pickle")

        elif output[:7] == "referer":
            # Add all plain result lines as info messages on redirect
            for l in api_cmd.__unicode__().splitlines():
                api_cmd.msglog.info("Result: {l}".format(l=l))
            response = django.shortcuts.redirect(output[7:] if output[7:] else request.META.get("HTTP_REFERER", "/"))
        else:
            response = django.http.HttpResponseBadRequest("<h1>Unknow output type '{o}'</h1>".format(o=output))

        # Add all user messages as as custom HTTP headers
        n = 0
        for l in reversed(api_cmd.msglog.plain.splitlines()):
            response["X-Mini-Buildd-Message-{n}".format(n=n)] = l
            n += 1
        return response

    except Exception as e:
        # This might as well be just an internal error; in case of no bug in the code, 405 fits better though.
        # ['wontfix' unless we refactor to diversified exception classes]
        mini_buildd.setup.log_exception(LOG, "API call error", e)
        return error405_method_not_allowed(request, "API call error: {e}".format(e=e), api_cmd=api_cmd)
