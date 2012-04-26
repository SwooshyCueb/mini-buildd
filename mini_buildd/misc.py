# -*- coding: utf-8 -*-
import sys
import os
import errno
import subprocess
import tempfile
import logging

import mini_buildd

log = logging.getLogger(__name__)

def codename2Version(codename):
    known = {
        'woody'  : "30",
        'sarge'  : "31",
        'etch'   : "40",
        'lenny'  : "50",
        'squeeze': "60",
        'wheezy' : "70",
        'sid'    : "SID",
        }
    try:
        return known[codename]
    except KeyError as e:
        raise Exception("Unknown codename: {c}".format(c=codename))

def mkdirs(path):
    try:
        os.makedirs(path)
        log.info("Directory created: {d}".format(d=path))
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise
        else:
            log.info("Directory already exists, ignoring; {d}".format(d=path))

def run_cmd(cmd):
    # Run command, keep output
    output = tempfile.TemporaryFile()
    log.info("Running system command: '%s'" % cmd)
    retval = subprocess.call([cmd], shell=True, stdout=output, stderr=subprocess.STDOUT)

    # Log command output
    l = log.info if (retval == 0) else log.error
    output.seek(0)
    for line in output:
        l("Command output: %s" % line.replace("\n", ""))

    if retval != 0:
        raise Exception("Command '{c}' failed with retval {r}".format(c=cmd, r=retval))

def get_cmd_stdout(cmd):
    output = tempfile.TemporaryFile()
    log.info("Running system command: '%s'" % cmd)
    retval = subprocess.call([cmd], shell=True, stdout=output, stderr=subprocess.STDOUT)
    if retval == 0:
        output.seek(0)
        return output.read()
    else:
        log.error("Command failed: %s" % cmd)
        return ""
