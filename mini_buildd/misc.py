# -*- coding: utf-8 -*-
import sys
import os
import errno
import subprocess
import threading
import tempfile
import hashlib
import logging

import mini_buildd

log = logging.getLogger(__name__)

class BindArgs(object):
    """ Convenience class to parse bind string "hostname:port" """
    def __init__(self, bind):
        try:
            self.string = bind
            triple = bind.rpartition(":")
            self.tuple = (triple[0], int(triple[2]))
            self.host = self.tuple[0]
            self.port = self.tuple[1]
        except:
            raise Exception("Invalid bind argument (HOST:PORT): '{b}'".format(b=bind))

def nop(*a,**k):
    pass

def start_thread(obj):
    thread = threading.Thread(target=obj.run)
    thread.setDaemon(True)
    thread.start()

def md5_of_file(fn):
    md5 = hashlib.md5()
    with open(fn) as f:
        while True:
            data = f.read(128)
            if not data:
                break
            md5.update(data)
    return md5.hexdigest()

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
            log.debug("Directory already exists, ignoring; {d}".format(d=path))

def run_cmd(cmd):
    # Run command, keep output
    output = tempfile.TemporaryFile()
    log.info("Running system command: '%s'" % cmd)
    retval = subprocess.call([cmd], shell=True, stdout=output, stderr=subprocess.STDOUT)

    # Log command output
    l = log.debug if (retval == 0) else log.error
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
