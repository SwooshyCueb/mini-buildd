# -*- coding: utf-8 -*-
"""
Manage schroots for mini-buildd.
"""

import os
import glob

import mini_buildd

def rfile(path):
    with open(path) as f:
        return f.read()

class LVMLoop():
    def __init__(self, path, arch, size):
        self._vgname = "mini-buildd-loop-{a}".format(a=arch)
        self._backing_file = os.path.join(path, "lvm.image")
        self._size = 100
        mini_buildd.log.debug("LVMLoop on {b}, size {s} G".format(b=self._backing_file, s=size))

    def get_loop_device(self):
        for f in glob.glob("/sys/block/loop[0-9]*/loop/backing_file"):
            if rfile(f).strip() == self._backing_file:
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
            mini_buildd.log.debug("LVMLoop: Image file created: '{b}' size {s}G".format(b=self._backing_file, s=self._size))

        # Check loop dev
        if self.get_loop_device() == None:
            mini_buildd.misc.run_cmd("sudo losetup -v -f {img}".format(img=self._backing_file))
            mini_buildd.log.debug("LVMLoop {d}@{b}: Loop device attached".format(d=self.get_loop_device(), b=self._backing_file))

        # Check lvm
        if not mini_buildd.misc.run_cmd("sudo vgchange --available y {vgname}".format(vgname=self._vgname)):
            mini_buildd.log.debug("LVMLoop {d}@{b}: Creating new LVM '{v}'".format(d=self.get_loop_device(), b=self._backing_file, v=self._vgname))
            mini_buildd.misc.run_cmd("sudo pvcreate -v '{dev}'".format(dev=self.get_loop_device()))
            mini_buildd.misc.run_cmd("sudo vgcreate -v '{vgname}' '{dev}'".format(vgname=self._vgname, dev=self.get_loop_device()))

        mini_buildd.log.info("LVMLoop prepared: {d}@{b} on {v}".format(d=self.get_loop_device(), b=self._backing_file, v=self._vgname))

    def purge(self):
        mini_buildd.misc.run_cmd("sudo lvremove --force {v}".format(v=self._vgname))
        mini_buildd.misc.run_cmd("sudo vgremove --force {v}".format(v=self._vgname))
        mini_buildd.misc.run_cmd("sudo pvremove {v}".format(v=self._vgname))
        mini_buildd.misc.run_cmd("sudo losetup -d {d}".format(d=self.get_lvm_device()))
        mini_buildd.misc.run_cmd("rm -f -v '{f}'".format(f=self._backing_file))

class Schroot():
    def __init__(self, builder):
        path = builder.get_path()
        mini_buildd.misc.mkdirs(path)

        if builder.schroot_mode == "lvm_loop":
            self._backend = LVMLoop(path, builder.arch, 100);

    def prepare(self):
        self._backend.prepare()

    def purge(self):
        self._backend.purge()
