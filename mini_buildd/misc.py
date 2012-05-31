# -*- coding: utf-8 -*-
import sys
import os
import errno
import subprocess
import threading
import tempfile
import hashlib
import logging

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

def nop(*args, **kwargs):
    pass

def start_thread(obj, *args, **kwargs):
    thread = threading.Thread(target=obj.run, args=args, kwargs=kwargs)
    thread.setDaemon(True)
    thread.start()
    return thread

def md5_of_file(fn):
    md5 = hashlib.md5()
    with open(fn) as f:
        while True:
            data = f.read(128)
            if not data:
                break
            md5.update(data)
    return md5.hexdigest()

def taint_env(taint):
    env = os.environ.copy()
    for e in taint:
        env[e] = taint[e]
    return env

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

def call(args, run_as_root=False, value_on_error=None, log_output=True, **kwargs):
    if run_as_root:
        args = ["sudo"] + args

    stdout = tempfile.TemporaryFile()
    stderr = tempfile.TemporaryFile()

    log.info("Calling: {a}".format(a=args))
    try:
        try:
            subprocess.check_call(args, stdout=stdout, stderr=stderr, **kwargs)
        finally:
            if log_output:
                stdout.seek(0)
                for line in stdout:
                    log.debug("Call stdout: {l}".format(l=line.rstrip('\n')))
                stderr.seek(0)
                for line in stderr:
                    log.debug("Call stderr: {l}".format(l=line.rstrip('\n')))
    except:
        log.error("Call failed: {a}".format(a=args))
        if value_on_error != None:
            return value_on_error
        else:
            raise
    log.info("Call successful: {a}".format(a=args))
    stdout.seek(0)
    return stdout.read()

def call_sequence(calls, run_as_root=False, value_on_error=None, log_output=True, rollback_only=False, **kwargs):
    def rollback(pos):
        for i in range(pos, -1, -1):
            if calls[i][1]:
                call(calls[i][1], run_as_root=run_as_root, value_on_error="", log_output=log_output, **kwargs)
            else:
                log.debug("Skipping empty rollback call sequent {i}".format(i=i))

    if rollback_only:
        rollback(len(calls)-1)
    else:
        i = 0
        try:
            for l in calls:
                if l[0]:
                    call(l[0], run_as_root=run_as_root, value_on_error=value_on_error, log_output=log_output, **kwargs)
                else:
                    log.debug("Skipping empty call sequent {i}".format(i=i))
                i += 1
        except:
            log.error("Sequence failed at: {i} (rolling back)".format(i=i))
            rollback(i)
            raise

def setup_test_logging():
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(levelname)-8s: %(message)s"))
    log.addHandler(h)
    log.setLevel(logging.DEBUG)

if __name__ == "__main__":
    setup_test_logging()
    print call(["id", "-u", "-n"])
    #print call(["id", "-syntax-error"], value_on_error="Kapott")
    print call(["id", "-syntax-error"], value_on_error="Kapott", log_output=False)

    print call(["env"], env=taint_env({"Kuh": "Sack"}))
    print call(["env"])

    call_sequence([
            (["echo", "cmd0"],    ["echo", "Rollback only: cmd0"]),
            (["echo", "cmd1"],    ["echo", "Rollback only: cmd1"]),
            (["echo", "cmd2"],    ["echo", "Rollback only: cmd2"]),
            (["false"],           ["echo", "Rollback only: cmd3"]),
            ], rollback_only=True, log_output=False)

    call_sequence([
            (["echo", "cmd0"],    ["echo", "Rollback: cmd0"]),
            (["echo", "cmd1"],    ["echo", "Rollback: cmd1"]),
            (["echo", "cmd2"],    ["echo", "Rollback: cmd2"]),
            (["false"],           ["echo", "Rollback: cmd3"]),
            ], run_as_root=True, log_output=False)
