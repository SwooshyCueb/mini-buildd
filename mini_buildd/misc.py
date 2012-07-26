# -*- coding: utf-8 -*-
import pprint
import os
import shutil
import errno
import subprocess
import threading
import multiprocessing
import tempfile
import hashlib
import pickle
import logging
import logging.handlers

LOG = logging.getLogger(__name__)


class HoPo(object):
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


class BuilderState(object):
    """ Builder status (de)serializer.

    >>> s = BuilderState(state=[True, u"host:324", 66, {"i386": ["squeeze", "sid"], "amd64": ["sid"]}])
    >>> s.is_up(), s.get_hopo().port, s.get_load(), s.has_chroot("amd64", "squeeze"), s.has_chroot("i386", "squeeze")
    (True, 324, 66, False, True)
    """

    def __init__(self, state=None, pickled_state=None):
        if state:
            self._state = state
        elif pickled_state:
            self._state = pickle.load(pickled_state)

    def __unicode__(self):
        return u"{s}: {h}: {c} ({l})".format(
            s=u"Running" if self.is_up() else u"Stopped",
            h=self.get_hopo().string,
            c=pprint.pformat(self.get_chroots()),
            l=self.get_load())

    def __str__(self):
        return self.__unicode__()

    def dump(self):
        return pickle.dumps(self._state)

    def is_up(self):
        return self._state[0]

    def get_hopo(self):
        return HoPo(self._state[1])

    def get_load(self):
        return self._state[2]

    def get_chroots(self):
        return self._state[3]

    def has_chroot(self, arch, codename):
        try:
            return codename in self.get_chroots()[arch]
        except:
            return False


def nop(*_args, **_kwargs):
    pass


def parse_distribution(dist):
    """Parse a mini-buildd distribution of the form CODENAME-ID-SUITE into a triple in that order.

    >>> parse_distribution("squeeze-test-unstable")
    ('squeeze', 'test', 'unstable')
    """
    dsplit = dist.split("-")
    if len(dsplit) != 3 or not dsplit[0] or not dsplit[1] or not dsplit[2]:
        raise Exception("Malformed distribution '{d}': Must be 'CODENAME-ID-SUITE'".format(d=dist))
    return dsplit[0], dsplit[1], dsplit[2]


def subst_placeholders(template, placeholders):
    """Substitue placeholders in string from a dict.

    >>> subst_placeholders("Repoversionstring: %IDENTITY%%CODEVERSION%", { "IDENTITY": "test", "CODEVERSION": "60" })
    'Repoversionstring: test60'
    """
    for key, value in placeholders.items():
        template = template.replace("%{p}%".format(p=key), value)
    return template


def fromdos(string):
    return string.replace('\r\n', '\n').replace('\r', '')


def run_as_thread(thread_func=None, daemon=False, **kwargs):
    def run(**kwargs):
        tid = thread_func.__module__ + "." + thread_func.__name__
        try:
            LOG.info("{i}: Starting...".format(i=tid))
            thread_func(**kwargs)
            LOG.info("{i}: Finished.".format(i=tid))
        except Exception as e:
            LOG.exception("{i}: Exception: {e}".format(i=tid, e=str(e)))
        except:
            LOG.exception("{i}: Non-standard exception".format(i=tid))

    thread = threading.Thread(target=run, kwargs=kwargs)
    thread.setDaemon(daemon)
    thread.start()
    return thread


def hash_of_file(file_name, hash_type="md5"):
    """
    Helper to get any hash from file contents.
    """
    md5 = hashlib.new(hash_type)
    with open(file_name) as f:
        while True:
            data = f.read(128)
            if not data:
                break
            md5.update(data)
    return md5.hexdigest()


def md5_of_file(file_name):
    return hash_of_file(file_name, hash_type="md5")


def sha1_of_file(file_name):
    return hash_of_file(file_name, hash_type="sha1")


def taint_env(taint):
    env = os.environ.copy()
    for name in taint:
        env[name] = taint[name]
    return env


def get_cpus():
    try:
        return multiprocessing.cpu_count()
    except:
        return 1


def mkdirs(path):
    try:
        os.makedirs(path)
        LOG.info("Directory created: {d}".format(d=path))
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise
        else:
            LOG.debug("Directory already exists, ignoring; {d}".format(d=path))


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

    LOG.info("Calling: {a}".format(a=args))
    try:
        olog = LOG.debug
        try:
            subprocess.check_call(args, stdout=stdout, stderr=stderr, **kwargs)
        except:
            olog = LOG.error
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
        LOG.error("Call failed: {a}".format(a=args))
        if value_on_error is not None:
            return value_on_error
        else:
            raise
    LOG.info("Call successful: {a}".format(a=args))
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
                LOG.debug("Skipping empty rollback call sequent {i}".format(i=i))

    if rollback_only:
        rollback(len(calls) - 1)
    else:
        i = 0
        try:
            for l in calls:
                if l[0]:
                    call(l[0], run_as_root=run_as_root, value_on_error=value_on_error, log_output=log_output, **kwargs)
                else:
                    LOG.debug("Skipping empty call sequent {i}".format(i=i))
                i += 1
        except:
            LOG.error("Sequence failed at: {i} (rolling back)".format(i=i))
            rollback(i)
            raise

SBUILD_KEYS_WORKAROUND_LOCK = threading.Lock()


def sbuild_keys_workaround():
    "Create sbuild's internal key if needed (sbuild needs this one-time call, but does not handle it itself)."
    with SBUILD_KEYS_WORKAROUND_LOCK:
        if os.path.exists("/var/lib/sbuild/apt-keys/sbuild-key.pub"):
            LOG.debug("/var/lib/sbuild/apt-keys/sbuild-key.pub: Already exists, skipping")
        else:
            t = tempfile.mkdtemp()
            LOG.warn("One-time generation of sbuild keys (may take some time)...")
            call(["sbuild-update", "--keygen"], env=taint_env({"HOME": t}))
            shutil.rmtree(t)
            LOG.info("One-time generation of sbuild keys done")


def setup_test_logging(syslog=True):
    if syslog:
        sh = logging.handlers.SysLogHandler(address="/dev/log", facility=logging.handlers.SysLogHandler.LOG_USER)
        sh.setFormatter(logging.Formatter("%(levelname)-8s: %(message)s"))
        LOG.addHandler(sh)

    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(levelname)-8s: %(message)s"))
    LOG.addHandler(ch)
    LOG.setLevel(logging.DEBUG)


if __name__ == "__main__":
    setup_test_logging()

    import doctest
    doctest.testmod()
