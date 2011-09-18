# coding: utf-8

"""mini-buildd: Command line options handling."""

import optparse
import logging
import os
import sys

import mini_buildd

def _fileopt_post(value, default):
    """Expand and make absolute for later use; check for file existence if not default."""

    # Normalize paths
    value = os.path.abspath(os.path.expanduser(value))
    default = os.path.abspath(os.path.expanduser(default))
    if not os.access(value, os.F_OK):
        if value != default:
            # Option given on command line
            print >>sys.stderr, "ERROR: The given file '%s' does not exist." % value
            sys.exit(1)
        else:
            value = None
    return value

def _run_default_log_config(option, opt, value, parser):
    print mini_buildd.log.get_default()
    sys.exit(0)

# Set up parser
parser = optparse.OptionParser(usage="Usage: %prog [options] [DIRECTORY]",
                               version="%prog-" + mini_buildd.version.pkg_version,
                               description="mini build daemon.")

# Set up options
parser.add_option("-f", "--foreground", action="store_true",
                     help="Don't daemonize, log to console.")
parser.add_option("-n", "--no-act", action="store_true",
                     help="Don't install anything, just log what we would do.")

group_log = optparse.OptionGroup(parser, "Logging")
group_log.add_option("-v", "--verbose", dest="verbosity", action="count", default=0,
                     help="Lower log level. Give twice for max logs.")
group_log.add_option("-q", "--quiet", dest="terseness", action="count", default=0,
                     help="Tighten log level. Give twice for min logs.")
group_log.add_option("-l", "--log-config", action="store", default="~/.mini-buildd-daemon.log.conf",
                     help="Log configuration file [%default].")
group_log.add_option("--print-default-log-config", action="callback", callback=_run_default_log_config,
                     help="Print internal default log configuration; used if you don't have a log config file.")
parser.add_option_group(group_log)

group_conf = optparse.OptionGroup(parser, "Daemon configuration")
group_conf.add_option("-H", "--home", action="store", default=os.getenv('HOME'),
                      help="Run with this home dir. The only use case to change this for debugging, really [%default].")
group_conf.add_option("-I", "--instdir", action="store", default="/usr/share/pyshared",
                      help="Run with this installation dir (where mini_buildd py mod is located [%default].")
parser.add_option_group(group_conf)

group_db = optparse.OptionGroup(parser, "Database")
group_db.add_option("-L", "--loaddata", action="store",
                      help="Import this *.json fixture or *.conf old 0.8.x-style config [%default].")
group_db.add_option("-E", "--dumpdata", action="store",
                      help="Export database [%default].")
parser.add_option_group(group_db)

# Parse
(opts, args) = parser.parse_args()

# Post-process file name options
opts.log_config  = _fileopt_post(opts.log_config, parser.defaults["log_config"])

# Now, implicitly configure mini-buildd logger; all code hereafter may use logging
mini_buildd.log.configure(opts.log_config, logging.WARNING-(10*(opts.verbosity-opts.terseness)), opts.foreground)
