# coding: utf-8

"""Logging for mini-buildd.

This module holds the gobal logger object 'log' for mini-buildd. To
use that name as shortcut, add

from mini_buildd.log import log

to your import lines. No other object in mini-buildd code should be
named 'log'.

Use the init() function early in your main code to configure the
logger.

"""

import StringIO
import logging
import logging.config
import logging.handlers


# The internal default log configuration.
# Per default, we log to syslog only, facility user, loglevel WARNING.
_DEFAULTS = StringIO.StringIO("""
[formatters]
keys: console,file,syslog

[handlers]
keys: console,file,syslog

[loggers]
keys: root,mini-buildd

[formatter_console]
format: %(name)s %(levelname)-8s: %(message)s [%(module)s:%(lineno)d]

[formatter_file]
format: %(asctime)s %(name)s %(levelname)-8s: %(message)s [%(module)s:%(lineno)d]

[formatter_syslog]
format: %(name)s %(levelname)-8s: %(message)s [%(module)s:%(lineno)d]

[handler_console]
class: StreamHandler
args: []
formatter: console

[handler_file]
class: FileHandler
args: [os.path.expanduser('~/.mini-buildd.log')]
formatter: file

[handler_syslog]
class: handlers.SysLogHandler
args: ['/dev/log', handlers.SysLogHandler.LOG_USER]
formatter: syslog

[logger_root]
level: WARNING
handlers:

# Basic custom configurations usually go here only (to handlers, level)
[logger_mini-buildd]
qualname: mini-buildd
handlers: syslog
level: WARNING
""")

def get_default():
    """Get default configuaration; this is used when no config file is found."""
    return _DEFAULTS.getvalue()

def configure(config, loglevel, debug):
    """Configure mini-buildd's global logger object."""

    if config:
        #print "Loading user logging conf %s" % config
        logging.config.fileConfig(config)
    else:
        #print "Using default logging configuration"
        logging.config.fileConfig(_DEFAULTS)

    # Set log level
    log.setLevel(loglevel)

    # On debug, add an extra handler for sys.stderr
    if debug:
        debugHandler = logging.StreamHandler()
        debugHandler.setFormatter(logging.Formatter("CONSOLE-LOG: %(levelname)-8s: %(message)s [%(module)s:%(lineno)d]"))
        log.addHandler(debugHandler)

    # Global: Don't propagate exceptions that happen while logging
    logging.raiseExceptions = 0

def _test():
    configure(None, logging.DEBUG, True)
    log.debug("LEVEL 'debug'")
    log.info("LEVEL 'info'")
    log.warning("LEVEL 'warning'")
    log.error("LEVEL 'error'")
    log.critical("LEVEL 'critical'")


# The global logger object
log = logging.getLogger("mini-buildd")

if __name__ == '__main__':
    _test()
else:
    pass
