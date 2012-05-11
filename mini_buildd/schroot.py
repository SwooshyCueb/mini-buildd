# -*- coding: utf-8 -*-
"""
Manage schroots for mini-buildd.
"""

import os
import glob
import tempfile
import getpass
import logging

import mini_buildd

log = logging.getLogger(__name__)

def rfile(path):
    with open(path) as f:
        return f.read()

class LVMLoop():
    """ This class provides some interesting LVM-(loop-)device stuff. """

    def __init__(self, path, arch, size):
        self._vgname = "mini-buildd-loop-{a}".format(a=arch)
        self._backing_file = os.path.join(path, "lvm.image")
        self._size = 100
        log.debug("LVMLoop on {b}, size {s} G".format(b=self._backing_file, s=size))

    def get_vgname(self):
        return self._vgname

    def get_loop_device(self):
        for f in glob.glob("/sys/block/loop[0-9]*/loop/backing_file"):
            if os.path.realpath(rfile(f).strip()) == os.path.realpath(self._backing_file):
                return "/dev/" + f.split("/")[3]

    def get_lvm_device(self):
        for f in glob.glob("/sys/block/loop[0-9]*/loop/backing_file"):
            if rfile(f).strip() == self._backing_file:
                return "/dev/" + f.split("/")[3]

    def prepare(self):
        # Check image file
        if not os.path.exists(self._backing_file):
            mini_buildd.misc.run_cmd("dd if=/dev/zero of='{imgfile}' bs='{gigs}M' seek=1024 count=0".format(\
                    imgfile=self._backing_file, gigs=self._size))
            log.debug("LVMLoop: Image file created: '{b}' size {s}G".format(b=self._backing_file, s=self._size))

        # Check loop dev
        if self.get_loop_device() == None:
            mini_buildd.misc.run_cmd("sudo losetup -v -f {img}".format(img=self._backing_file))
            log.debug("LVMLoop {d}@{b}: Loop device attached".format(d=self.get_loop_device(), b=self._backing_file))

        # Check lvm
        try:
            mini_buildd.misc.run_cmd("sudo vgchange --available y {vgname}".format(vgname=self._vgname))
        except:
            log.debug("LVMLoop {d}@{b}: Creating new LVM '{v}'".format(d=self.get_loop_device(), b=self._backing_file, v=self._vgname))
            mini_buildd.misc.run_cmd("sudo pvcreate -v '{dev}'".format(dev=self.get_loop_device()))
            mini_buildd.misc.run_cmd("sudo vgcreate -v '{vgname}' '{dev}'".format(vgname=self._vgname, dev=self.get_loop_device()))

        log.info("LVMLoop prepared: {d}@{b} on {v}".format(d=self.get_loop_device(), b=self._backing_file, v=self._vgname))

    def purge(self):
        try:
            mini_buildd.misc.run_cmd("sudo lvremove --force {v}".format(v=self._vgname))
            mini_buildd.misc.run_cmd("sudo vgremove --force {v}".format(v=self._vgname))
            mini_buildd.misc.run_cmd("sudo pvremove {v}".format(v=self._vgname))
            mini_buildd.misc.run_cmd("sudo losetup -d {d}".format(d=self.get_lvm_device()))
            mini_buildd.misc.run_cmd("rm -f -v '{f}'".format(f=self._backing_file))
        except:
            log.warn("[@todo: better log:] Some purging steps may have failed")


class Schroot():
    """
    This class provides some schroot features.

    .. note::
       It makes use of :class:`LVMLoop`.
    """

    def __init__(self, builder):
        self.CHROOT_FS="ext2"

        path = builder.get_path()
        mini_buildd.misc.mkdirs(path)
        self.builder = builder
        if builder.schroot_mode == "lvm_loop":
            self._backend = LVMLoop(path, builder.arch, 100);

    def get_personality(self):
        """
        On 64bit hosts, 32bit schroots must be configured
        with a *linux32* personality to work.

        .. todo::
           - This may be needed for other 32-bit archs, too?
           - We currently assume we build under linux only.
        """
        personalities = { 'i386': 'linux32' }
        try:
            return personalities[self.builder.arch.arch]
        except:
            return "linux"

    def prepare(self):
        self._backend.prepare()

        for dist in self.builder.dists.all():
            name = "mini-buildd-{d}-{a}".format(d=dist.base_source.codename, a=self.builder.arch.arch)
            device = "/dev/{v}/{n}".format(v=self._backend.get_vgname(), n=name)

            try:
                mini_buildd.misc.run_cmd("sudo lvdisplay | grep -q '{c}'".format(c=name))
                log.info("LV {c} exists, leaving alone".format(c=name))
            except:
                log.info("Setting up LV {c}...".format(c=name))

                mirror=dist.base_source.mirrors.all()[0]
                log.info("Found mirror for {n}: {M} ".format(n=name, M=mirror))

                # @todo aptenv ??
                #mbdAptEnv

                mount_point = tempfile.mkdtemp()
                try:
                    mini_buildd.misc.run_cmd("sudo lvcreate -L 4G -n '{n}' '{v}'".format(n=name, v=self._backend.get_vgname()))
                    mini_buildd.misc.run_cmd("sudo mkfs.{f} '{d}'".format(f=self.CHROOT_FS, d=device))
                    mini_buildd.misc.run_cmd("sudo mount -v -t{f} '{d}' '{m}'".format(f=self.CHROOT_FS, d=device, m=mount_point))
                    # @todo include=sudo is only workaround for sbuild Bug #608840
                    # @todo include=apt WTF?
                    mini_buildd.misc.run_cmd("sudo debootstrap --variant='buildd' --arch='{a}' --include='apt,sudo' '{d}' '{m}' '{M}'".\
                                                 format(a=self.builder.arch.arch, d=dist.base_source.codename, m=mount_point, M=mirror))

                    # @todo Still sudoers workaround
                    with tempfile.NamedTemporaryFile() as ts:
                        ts.write("""
{u}	ALL=(ALL) ALL
{u}	ALL=NOPASSWD: ALL
""".format(u=getpass.getuser()))
                        ts.flush()
                        mini_buildd.misc.run_cmd("sudo cp '{ts}' '{m}/etc/sudoers'".format(ts=ts.name, m=mount_point))
                    # @todo End sudoers workaround

                    mini_buildd.misc.run_cmd("sudo umount -v '{m}'".format(m=mount_point))
                    log.info("LV {n} created successfully...".format(n=name))
                    # There must be schroot configs for each uploadable distribution (does not work with aliases).
                    open(os.path.join(self.builder.get_path(), "schroot.conf"), 'w').write("""
[{n}]
type=lvm-snapshot
description=Mini-Buildd {n} LVM snapshot chroot
groups=sbuild
users=mini-buildd
root-groups=sbuild
root-users=mini-buildd
source-root-users=mini-buildd
device={d}
mount-options=-t {f} -o noatime,user_xattr
lvm-snapshot-options=--size 4G
personality={p}
""".format(n=name, d=device, f=self.CHROOT_FS, p=self.get_personality()))
                except:
                    log.info("LV {n} creation FAILED. Rewinding...".format(n=name))
                    try:
                        mini_buildd.misc.run_cmd("sudo umount -v '{m}'".format(m=mount_point))
                        mini_buildd.misc.run_cmd("sudo lvremove --force '{d}'".format(d=device))
                    except:
                        pass
                    raise

    def purge(self):
        # @todo
        for dist in self.builder.dists.all():
            log.error("@todo NOT IMPL PURGE")
        #self._backend.purge()
