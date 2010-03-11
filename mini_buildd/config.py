# coding: utf-8

"Config file handling for mini-buildd."

import ConfigParser
import StringIO
import os

from mini_buildd.log import log

_DEFAULTS = {
    "no_options_yet_dummy": "123"
    }

config = ConfigParser.ConfigParser()

def get_default():
    """Get default configuaration string."""
    config = ConfigParser.ConfigParser(_DEFAULTS)
    dummy = StringIO.StringIO()
    config.write(dummy)
    return dummy.getvalue()

def configure(file):
    """Configure from file."""
    global config
    log.debug("Setting default config")
    config = ConfigParser.ConfigParser(_DEFAULTS)
    if file:
        log.info("Reading configuration from %s" % file)
        config.read(file)
