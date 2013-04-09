# -*- coding: utf-8 -*-
from __future__ import unicode_literals

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


def _add_messages(response, msgs1, msgs2):
    "Add all texts in messages (must be one line each) as custom HTTP headers"
    n = 0
    for msg in msgs2:
        response["X-Mini-Buildd-Message-{n}".format(n=n)] = msg
        n += 1

    for msg in msgs1:
        response["X-Mini-Buildd-Message-{n}".format(n=n)] = msg
        n += 1


def _add_api_messages(response, api_cmd, msgs=None):
    "Add all user messages from api_cmd, plus optional extra messages."
    _add_messages(response,
                  reversed(api_cmd.msglog.plain.splitlines()) if api_cmd else [],
                  msgs if msgs else [])


def error(request, code, meaning, description, api_cmd=None):
    # Note: Adding api_cmd if applicable; this will enable automated api links even on error pages.
    response = django.shortcuts.render(request,
                                       "mini_buildd/error.html",
                                       {"code": code,
                                        "meaning": meaning,
                                        "description": description,
                                        "api_cmd": api_cmd},
                                       status=code)
    _add_api_messages(response, api_cmd, ["E: {d}".format(d=description)])
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
        pkg_log = mini_buildd.misc.PkgLog(repository, installed, package, version)

        return {"changes": open(pkg_log.changes).read() if pkg_log.changes else None,
                "changes_path": pkg_log.make_relative(pkg_log.changes) if pkg_log.changes else None,
                "buildlogs": dict((k, pkg_log.make_relative(v)) for k, v in pkg_log.buildlogs.iteritems())}

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

        # Call API index if called with no argument
        if not request.GET:
            cmd_objs = {}
            for cmd, cls in mini_buildd.api.COMMANDS.items():
                cmd_objs[cmd] = cls(cls.get_default_args())
            return django.shortcuts.render_to_response("mini_buildd/api_index.html",
                                                       {"COMMANDS": cmd_objs},
                                                       django.template.RequestContext(request))

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
        _add_api_messages(response, api_cmd)

        return response

    except Exception as e:
        # This might as well be just an internal error; in case of no bug in the code, 405 fits better though.
        # ['wontfix' unless we refactor to diversified exception classes]
        mini_buildd.setup.log_exception(LOG, "API call error", e)
        return error405_method_not_allowed(request, "API call error: {e}".format(e=e), api_cmd=api_cmd)
