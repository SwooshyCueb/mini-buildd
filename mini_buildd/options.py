# -*- coding: utf-8 -*-
"""
mini-buildd: Command line options handling.
"""

import string
import optparse
import logging
import logging.handlers
import os
import sys

import mini_buildd

# Set up parser
parser = optparse.OptionParser(usage="Usage: %prog [options] [DIRECTORY]",
                               version="%prog-" + mini_buildd.__version__,
                               description="mini build daemon.")

# Set up options
parser.add_option("-f", "--foreground", action='store_true',
                  help="Don't daemonize, log to console.")
parser.add_option("-n", "--no-act", action='store_true',
                  help="Don't install anything, just log what we would do.")
parser.add_option("-B", "--bind", action='store', default=":8066",
                  help="Hostname and port to bind to.")

group_log = optparse.OptionGroup(parser, "Logging")
group_log.add_option("-v", "--verbose", dest="verbosity", action='count', default=0,
                     help="Lower log level. Give twice for max logs.")
group_log.add_option("-q", "--quiet", dest="terseness", action='count', default=0,
                     help="Tighten log level. Give twice for min logs.")
group_log.add_option("-l", "--loggers", action='store', default="syslog",
                     help="Comma-separated list of loggers (syslog, console, file) to use [%default].")
parser.add_option_group(group_log)

group_conf = optparse.OptionGroup(parser, "Daemon configuration")
group_conf.add_option("-H", "--home", action='store', default=os.getenv('HOME'),
                      help="Run with this home dir. The only use case to change this for debugging, really [%default].")
group_conf.add_option("-I", "--instdir", action='store', default="/usr/share/pyshared",
                      help="Run with this installation dir (where mini_buildd python module is located). [%default].")
parser.add_option_group(group_conf)

group_db = optparse.OptionGroup(parser, "Database")
group_db.add_option("-L", "--loaddata", action='store', metavar="FILE",
                    help="Import FILE to django database and exit. FILE is a absolute or relative (to 'INSTDIR/fixtures/') \
django fixture path (see 'django-admin dumpdata'), or an absolute path /PATH/*.conf for an old 0.8.x-style config.")

group_db.add_option("-D", "--dumpdata", action='store', metavar="APP[.MODEL]",
                    help="Dump app[.MODEL] from django database and exit (see 'django-admin loaddata').")
parser.add_option_group(group_db)

# Parse
(opts, args) = parser.parse_args()

# Set up logging; "log" is global for mini_buildd, django is forced to use the same logging
log = logging.getLogger("mini-buildd")
django_log = logging.getLogger("django")

# Global: Don't propagate exceptions that happen while logging
logging.raiseExceptions = 0

# Add predefinded handlers: console, syslog, file
_LOG_HANDLERS = {}
_LOG_HANDLERS["syslog"] = logging.handlers.SysLogHandler(address="/dev/log", facility=logging.handlers.SysLogHandler.LOG_USER)
_LOG_HANDLERS["console"] = logging.StreamHandler()
_LOG_HANDLERS["file"] = logging.FileHandler(opts.home + "/.mini-buildd.log")

for h in string.split(opts.loggers + (",console" if opts.foreground else ""), ","):
    _LOG_HANDLERS[h].setFormatter(logging.Formatter("mini-buildd(%(name)s): %(levelname)-8s: %(message)s [%(module)s:%(lineno)d]"))
    log.addHandler(_LOG_HANDLERS[h])
    django_log.addHandler(_LOG_HANDLERS[h])

# Finally, set log level
loglevel=logging.WARNING-(10*(min(2, opts.verbosity)-min(2, opts.terseness)))
log.setLevel(loglevel)
django_log.setLevel(loglevel)
