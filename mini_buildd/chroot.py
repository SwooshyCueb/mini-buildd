# -*- coding: utf-8 -*-
import os
import re
import glob
import tempfile
import getpass
import logging

import django.db

import mini_buildd.globals
import mini_buildd.misc

log = logging.getLogger(__name__)

from mini_buildd.models import Distribution
from mini_buildd.models import Architecture
class Chroot(django.db.models.Model):
    dist = django.db.models.ForeignKey(Distribution)
    arch = django.db.models.ForeignKey(Architecture)
    filesystem = django.db.models.CharField(max_length=30, default="ext2")

    def get_path(self):
        return os.path.join(mini_buildd.globals.CHROOTS_DIR, self.dist.base_source.codename, self.arch.arch)

    def get_personality(self):
        """
        On 64bit hosts, 32bit schroots must be configured
        with a *linux32* personality to work.

        .. todo:: Chroot personalities

           - This may be needed for other 32-bit archs, too?
           - We currently assume we build under linux only.
        """
        personalities = { 'i386': 'linux32' }
        try:
            return personalities[self.arch.arch]
        except:
            return "linux"

    def prepare(self):
        """
        .. todo:: Chroot prepare

           - mbdAptEnv ??
           - include=sudo is only workaround for sbuild Bug #608840
           - debootstrap include=apt WTF?
        """
        log.info("Preparing '{d}' builder for '{a}'".format(d=self.dist.base_source.codename, a=self.arch))
        mini_buildd.misc.mkdirs(self.get_path())

        # TODO multi backends
        backend = self.lvmloopchroot
        backend.prepare()

        dist = self.dist

        name = "mini-buildd-{d}-{a}".format(d=dist.base_source.codename, a=self.arch.arch)
        device = "/dev/{v}/{n}".format(v=backend.get_vgname(), n=name)

        try:
            mini_buildd.misc.run_cmd("sudo lvdisplay | grep -q '{c}'".format(c=name))
            log.info("LV {c} exists, leaving alone".format(c=name))
        except:
            log.info("Setting up LV {c}...".format(c=name))

            mirror=dist.base_source.mirrors.all()[0]
            log.info("Found mirror for {n}: {M} ".format(n=name, M=mirror))

            mount_point = tempfile.mkdtemp()
            try:
                mini_buildd.misc.run_cmd("sudo lvcreate -L 4G -n '{n}' '{v}'".format(n=name, v=backend.get_vgname()))
                mini_buildd.misc.run_cmd("sudo mkfs.{f} '{d}'".format(f=self.filesystem, d=device))
                mini_buildd.misc.run_cmd("sudo mount -v -t{f} '{d}' '{m}'".format(f=self.filesystem, d=device, m=mount_point))

                # START SUDOERS WORKAROUND (remove --include=sudo when fixed)
                mini_buildd.misc.run_cmd("sudo debootstrap --variant='buildd' --arch='{a}' --include='apt,sudo' '{d}' '{m}' '{M}'".\
                                             format(a=self.arch.arch, d=dist.base_source.codename, m=mount_point, M=mirror))

                # STILL SUDOERS WORKAROUND (remove all when fixed)
                with tempfile.NamedTemporaryFile() as ts:
                    ts.write("""
{u}	ALL=(ALL) ALL
{u}	ALL=NOPASSWD: ALL
""".format(u=getpass.getuser()))
                    ts.flush()
                    mini_buildd.misc.run_cmd("sudo cp '{ts}' '{m}/etc/sudoers'".format(ts=ts.name, m=mount_point))
                # END SUDOERS WORKAROUND

                mini_buildd.misc.run_cmd("sudo umount -v '{m}'".format(m=mount_point))
                log.info("LV {n} created successfully...".format(n=name))
                # There must be schroot configs for each uploadable distribution (does not work with aliases).
                open(os.path.join(self.get_path(), "schroot.conf"), 'w').write("""
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
""".format(n=name, d=device, f=self.filesystem, p=self.get_personality()))
            except:
                log.info("LV {n} creation FAILED. Rewinding...".format(n=name))
                try:
                    mini_buildd.misc.run_cmd("sudo umount -v '{m}'".format(m=mount_point))
                    mini_buildd.misc.run_cmd("sudo lvremove --force '{d}'".format(d=device))
                except:
                    pass
                raise

    def purge(self):
        ".. todo:: chroot purge not implemented"
        log.error("NOT IMPL PURGE")

    def __unicode__(self):
        return "Chroot: {c}:{a}".format(c=self.dist.base_source.codename, a=self.arch.arch)

class LVMLoopChroot(Chroot):
    """ This class provides some interesting LVM-(loop-)device stuff. """

    def __init__(self, *args, **kwargs):
        super(LVMLoopChroot, self).__init__(*args, **kwargs)
        self._size = 100

    def get_vgname(self):
        return "mini-buildd-loop-{d}-{a}".format(d=self.dist.base_source.codename, a=self.arch.arch)

    def get_backing_file(self):
        return os.path.join(self.get_path(), "lvmloop.image")

    def get_loop_device(self):
        for f in glob.glob("/sys/block/loop[0-9]*/loop/backing_file"):
            if os.path.realpath(open(f).read().strip()) == os.path.realpath(self.get_backing_file()):
                return "/dev/" + f.split("/")[3]

    def get_lvm_device(self):
        for f in glob.glob("/sys/block/loop[0-9]*/loop/backing_file"):
            if open(f).read().strip() == self.get_backing_file():
                return "/dev/" + f.split("/")[3]

    def prepare(self):
        # Check image file
        if not os.path.exists(self.get_backing_file()):
            mini_buildd.misc.run_cmd("dd if=/dev/zero of='{imgfile}' bs='{gigs}M' seek=1024 count=0".format(\
                    imgfile=self.get_backing_file(), gigs=self._size))
            log.debug("LVMLoop: Image file created: '{b}' size {s}G".format(b=self.get_backing_file(), s=self._size))

        # Check loop dev
        if self.get_loop_device() == None:
            mini_buildd.misc.run_cmd("sudo losetup -v -f {img}".format(img=self.get_backing_file()))
            log.debug("LVMLoop {d}@{b}: Loop device attached".format(d=self.get_loop_device(), b=self.get_backing_file()))

        # Check lvm
        try:
            mini_buildd.misc.run_cmd("sudo vgchange --available y {vgname}".format(vgname=self.get_vgname()))
        except:
            log.debug("LVMLoop {d}@{b}: Creating new LVM '{v}'".format(d=self.get_loop_device(), b=self.get_backing_file(), v=self.get_vgname()))
            mini_buildd.misc.run_cmd("sudo pvcreate -v '{dev}'".format(dev=self.get_loop_device()))
            mini_buildd.misc.run_cmd("sudo vgcreate -v '{vgname}' '{dev}'".format(vgname=self.get_vgname(), dev=self.get_loop_device()))

        log.info("LVMLoop prepared: {d}@{b} on {v}".format(d=self.get_loop_device(), b=self.get_backing_file(), v=self.get_vgname()))

    def purge(self):
        try:
            mini_buildd.misc.run_cmd("sudo lvremove --force {v}".format(v=self.get_vgname()))
            mini_buildd.misc.run_cmd("sudo vgremove --force {v}".format(v=self.get_vgname()))
            mini_buildd.misc.run_cmd("sudo pvremove {v}".format(v=self.get_vgname()))
            mini_buildd.misc.run_cmd("sudo losetup -d {d}".format(d=self.get_lvm_device()))
            mini_buildd.misc.run_cmd("rm -f -v '{f}'".format(f=self.get_backing_file()))
        except:
            log.warn("LVM {n}: Some purging steps may have failed".format(n=self.get_vgname()))
