# coding: utf-8

"""mini-buildd: Command line options handling."""

# Python
import optparse
import logging
import os
import sys

# Local
import mini_buildd.version
import mini_buildd.config

# Local shortcuts
from mini_buildd.log import log


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

def _run_default_config(option, opt, value, parser):
    print mini_buildd.config.get_default()
    sys.exit(0)

def _run_default_log_config(option, opt, value, parser):
    print mini_buildd.log.get_default()
    sys.exit(0)

def _inc_loglevel(option, opt, value, parser):
    parser.values.loglevel = min(logging.CRITICAL, parser.values.loglevel+10)

def _dec_loglevel(option, opt, value, parser):
    parser.values.loglevel = max(logging.DEBUG, parser.values.loglevel-10)

# Set up parser
parser = optparse.OptionParser(usage="Usage: %prog [options] [DIRECTORY]",
                               version="%prog " + mini_buildd.version.pkg_version,
                               description="mini build daemon.")

# Set up options
parser.add_option("-f", "--foreground", action="store_true",
                     help="Don't daemonize, log to console.")
parser.add_option("-n", "--no-act", action="store_true",
                     help="Don't install anything, just log what we would do.")

group_conf = optparse.OptionGroup(parser, "Daemon configuration")
group_conf.add_option("-c", "--config", action="store",
                      help="Configuration file [%default].")
group_conf.add_option("--print-default-config", action="callback", callback=_run_default_config,
                help="Print internal default configuration; used if you don't have a config file.")
parser.add_option_group(group_conf)

group_log = optparse.OptionGroup(parser, "Logging")
group_log.add_option("-v", "--verbose", action="callback", dest="loglevel", callback=_dec_loglevel,
                     help="Lower log level. Give twice for max logs.")
group_log.add_option("-q", "--quiet", action="callback", dest="loglevel", callback=_inc_loglevel,
                     help="Tighten log level. Give twice for min logs.")
group_log.add_option("-l", "--log-config", action="store",
                     help="Log configuration file [%default].")
group_log.add_option("--print-default-log-config", action="callback", callback=_run_default_log_config,
                     help="Print internal default log configuration; used if you don't have a log config file.")
parser.add_option_group(group_log)

# Default values
parser.set_defaults(loglevel=logging.WARNING, console_log=False,
                    config='~/.mini-buildd-daemon.conf', log_config='~/.mini-buildd-daemon.log.conf')

# Parse
(opts, args) = parser.parse_args()

# Post-process file name options
opts.config  = _fileopt_post(opts.config, parser.defaults["config"])
opts.log_config  = _fileopt_post(opts.log_config, parser.defaults["log_config"])

# Now, implicitly configure mini-buildd logger; all code hereafter may use logging
mini_buildd.log.configure(opts.log_config, opts.loglevel, opts.foreground)

# Now, implicitly configure mini-buildd file configuration
mini_buildd.config.configure(opts.config)
