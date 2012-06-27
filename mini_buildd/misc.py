# -*- coding: utf-8 -*-
import sys, os, shutil, errno, subprocess, threading, multiprocessing, tempfile, hashlib, logging

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

def parse_distribution(dist):
    """Parse a mini-buildd distribution of the form BASE-ID-SUITE into a triple in that order.

    >>> parse_distribution("squeeze-test-unstable")
    ('squeeze', 'test', 'unstable')
    """
    dist_split = dist.split("-")
    base = dist_split[0]
    identity = dist_split[1]
    suite = dist_split[2]
    return base, identity, suite


def subst_placeholders(s, p):
    """Substitue placeholders in string from a dict.

    >>> subst_placeholders("Repoversionstring: %IDENTITY%%CODEVERSION%", { "IDENTITY": "test", "CODEVERSION": "60" })
    'Repoversionstring: test60'
    """
    for key, value in p.items():
        s = s.replace("%{p}%".format(p=key), value)
    return s

def fromdos(s):
    return s.replace('\r\n', '\n').replace('\r', '')

def run_as_thread(call=None, daemon=False, **kwargs):
    def run(**kwargs):
        id = call.__module__ + "." + call.__name__
        try:
            log.info("{i}: Starting...".format(i=id))
            call(**kwargs)
            log.info("{i}: Finished.".format(i=id))
        except Exception as e:
            log.exception("{i}: Exception: {e}".format(i=id, e=str(e)))
        except:
            log.exception("{i}: Non-standard exception".format(i=id))

    thread = threading.Thread(target=run, kwargs=kwargs)
    thread.setDaemon(daemon)
    thread.start()
    return thread

def hash_of_file(fn, hash_type=hashlib.md5):
    md5 = hash_type()
    with open(fn) as f:
        while True:
            data = f.read(128)
            if not data:
                break
            md5.update(data)
    return md5.hexdigest()

def md5_of_file(fn):
    return hash_of_file(fn, hash_type=hashlib.md5)

def sha1_of_file(fn):
    return hash_of_file(fn, hash_type=hashlib.sha1)

def taint_env(taint):
    env = os.environ.copy()
    for e in taint:
        env[e] = taint[e]
    return env

def get_cpus():
    try:
        return multiprocessing.cpu_count()
    except:
        return 1

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
    """Wrapper around subprocess.call().

    >>> call(["echo", "-n", "hallo"])
    'hallo'
    >>> call(["id", "-syntax-error"], value_on_error="Kapott")
    'Kapott'
    """

    if run_as_root:
        args = ["sudo"] + args

    stdout = tempfile.TemporaryFile()
    stderr = tempfile.TemporaryFile()

    log.info("Calling: {a}".format(a=args))
    try:
        olog = log.debug
        try:
            subprocess.check_call(args, stdout=stdout, stderr=stderr, **kwargs)
        except:
            olog=log.error
            raise
        finally:
            if log_output:
                stdout.seek(0)
                for line in stdout:
                    olog("Call stdout: {l}".format(l=line.rstrip('\n')))
                stderr.seek(0)
                for line in stderr:
                    olog("Call stderr: {l}".format(l=line.rstrip('\n')))
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
    """Run sequences of calls with rolbback support.

    >>> call_sequence([(["echo", "-n", "cmd0"], ["echo", "-n", "rollback cmd0"])])
    >>> call_sequence([(["echo", "cmd0"], ["echo", "rollback cmd0"])], rollback_only=True)
    """

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

sbuild_keys_workaround_lock = threading.Lock()

def sbuild_keys_workaround():
    "Create sbuild's internal key if needed (sbuild needs this one-time call, but does not handle it itself)."
    with sbuild_keys_workaround_lock:
        if os.path.exists("/var/lib/sbuild/apt-keys/sbuild-key.pub"):
            log.debug("/var/lib/sbuild/apt-keys/sbuild-key.pub: Already exists, skipping")
        else:
            t = tempfile.mkdtemp()
            log.warn("One-time generation of sbuild keys (may take some time)...")
            call(["sbuild-update", "--keygen"], env=taint_env({"HOME": t}))
            shutil.rmtree(t)
            log.info("One-time generation of sbuild keys done")


def setup_test_logging(syslog=True):
    if syslog:
        import logging.handlers
        sh = logging.handlers.SysLogHandler(address="/dev/log", facility=logging.handlers.SysLogHandler.LOG_USER)
        sh.setFormatter(logging.Formatter("%(levelname)-8s: %(message)s"))
        log.addHandler(sh)

    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(levelname)-8s: %(message)s"))
    log.addHandler(ch)
    log.setLevel(logging.DEBUG)

if __name__ == "__main__":
    setup_test_logging()

    import doctest
    doctest.testmod()
