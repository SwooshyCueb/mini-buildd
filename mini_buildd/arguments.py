# -*- coding: utf-8 -*-
"""
mini-buildd: Command line arguments handling.
"""

import string
import argparse
import logging
import logging.handlers
import os
import sys

import mini_buildd

# Set up parser
parser = argparse.ArgumentParser(prog="mini-buildd",
                                 description="mini build daemon.",
                                 formatter_class=argparse.ArgumentDefaultsHelpFormatter)

parser.add_argument('--version', action='version', version=mini_buildd.__version__)

# Set up arguments
parser.add_argument("-f", "--foreground", action='store_true',
                    help="Don't daemonize, log to console.")
parser.add_argument("-n", "--no-act", action='store_true',
                    help="Don't install anything, just log what we would do.")
parser.add_argument("-W", "--webserver-bind", action='store', default="0.0.0.0:8066",
                    help="Web Server IP/Hostname and port to bind to.")
parser.add_argument("-F", "--ftpserver-bind", action='store', default="0.0.0.0:8067",
                    help="FTP Server IP/Hostname and port to bind to.")

group_log = parser.add_argument_group("Logging")
group_log.add_argument("-v", "--verbose", dest="verbosity", action='count', default=0,
                       help="Lower log level. Give twice for max logs.")
group_log.add_argument("-q", "--quiet", dest="terseness", action='count', default=0,
                       help="Tighten log level. Give twice for min logs.")
group_log.add_argument("-l", "--loggers", action='store', default="syslog",
                       help="Comma-separated list of loggers (syslog, console, file) to use.")

group_conf = parser.add_argument_group("Daemon configuration")
group_conf.add_argument("-H", "--home", action='store', default=os.getenv('HOME'),
                        help="Run with this home dir. The only use case to change this for debugging, really.")
group_conf.add_argument("-I", "--instdir", action='store', default="/usr/share/pyshared",
                        help="Run with this installation dir (where mini_buildd python module is located).")

group_db = parser.add_argument_group("Database")
group_db.add_argument("-P", "--set-admin-password", action='store', metavar="PASSWORD",
                      help="Update password for django superuser named 'admin'; user is created if non-existent yet.")
group_db.add_argument("-C", "--create-default-config", action='store', metavar="MIRROR_URL",
                      help="Create an initial default config.")
group_db.add_argument("-L", "--loaddata", action='store', metavar="FILE",
                      help="Import FILE to django database and exit. FILE is a absolute or relative (to 'INSTDIR/fixtures/') \
django fixture path (see 'django-admin dumpdata'), or an absolute path /PATH/*.conf for an old 0.8.x-style config.")
group_db.add_argument("-D", "--dumpdata", action='store', metavar="APP[.MODEL]",
                      help="Dump app[.MODEL] from django database and exit (see 'django-admin loaddata').")

# Parse
args = parser.parse_args()

# Set up logging; "log" is global for mini_buildd, django is forced to use the same logging
log = logging.getLogger("mini-buildd")
django_log = logging.getLogger("django")

# Global: Don't propagate exceptions that happen while logging
logging.raiseExceptions = 0

# Add predefinded handlers: console, syslog, file
_LOG_HANDLERS = {}
_LOG_HANDLERS["syslog"] = logging.handlers.SysLogHandler(address="/dev/log", facility=logging.handlers.SysLogHandler.LOG_USER)
_LOG_HANDLERS["console"] = logging.StreamHandler()
_LOG_HANDLERS["file"] = logging.FileHandler(args.home + "/.mini-buildd.log")

for h in string.split(args.loggers + (",console" if args.foreground else ""), ","):
    _LOG_HANDLERS[h].setFormatter(logging.Formatter("mini-buildd(%(name)s): %(levelname)-8s: %(message)s [%(module)s:%(lineno)d]"))
    log.addHandler(_LOG_HANDLERS[h])
    django_log.addHandler(_LOG_HANDLERS[h])

# Finally, set log level
loglevel=logging.WARNING-(10*(min(2, args.verbosity)-min(2, args.terseness)))
log.setLevel(loglevel)
django_log.setLevel(loglevel)
