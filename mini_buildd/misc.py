# coding: utf-8

import sys
import os
import subprocess
import tempfile

from mini_buildd.log import log

def run_cmd(cmd, no_act):
    # Run command, keep output
    output = tempfile.TemporaryFile()
    if no_act:
        output.write("No-act mode: '%s' not run" % cmd)
        retval = 0
    else:
        log.info("Running system command: '%s'" % cmd)
        retval = subprocess.call([cmd], shell=True, stdout=output, stderr=subprocess.STDOUT)

    # Log command output
    l = log.info if (retval == 0) else log.error
    output.seek(0)
    for line in output:
        l("Command output: %s" % line.replace("\n", ""))
    l("Command '%s' run with retval %s" % (cmd, retval))

    return retval == 0
