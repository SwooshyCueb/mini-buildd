# -*- coding: utf-8 -*-
import os
import re
import glob
import tempfile
import pwd
import logging

import django.db

from mini_buildd import globals, misc

log = logging.getLogger(__name__)

class Chroot(django.db.models.Model):
    from mini_buildd.models import Distribution, Architecture
    dist = django.db.models.ForeignKey(Distribution)
    arch = django.db.models.ForeignKey(Architecture)

    def __unicode__(self):
        return "Chroot: {c}:{a}".format(c=self.dist.base_source.codename, a=self.arch.arch)

    class Meta:
        unique_together = ("dist", "arch")

    PERSONALITIES = { 'i386': 'linux32' }

    def get_backend(self):
        try:
            return self.filechroot
        except:
            try:
                return self.lvmloopchroot
            except:
                raise Exception("No chroot backend found")

    def get_path(self):
        return os.path.join(globals.CHROOTS_DIR, self.dist.base_source.codename, self.arch.arch)

    def get_name(self):
        return "mini-buildd-{d}-{a}".format(d=self.dist.base_source.codename, a=self.arch.arch)

    def get_tmp_dir(self):
        d = os.path.join(self.get_path(), "tmp")
        misc.mkdirs(d)
        return d

    def get_personality(self):
        """
        On 64bit hosts, 32bit schroots must be configured
        with a *linux32* personality to work.

        .. todo:: Chroot personalities

           - This may be needed for other 32-bit archs, too?
           - We currently assume we build under linux only.
        """
        try:
            return self.PERSONALITIES[self.arch.arch]
        except:
            return "linux"

    def debootstrap(self, dir):
        """
        .. todo:: debootstrap

           - mbdAptEnv ??
           - include=sudo is only workaround for sbuild Bug #608840
           - debootstrap include=apt WTF?
        """

        # START SUDOERS WORKAROUND (remove --include=sudo when fixed)
        misc.call(["debootstrap",
                   "--variant=buildd",
                   "--arch={a}".format(a=self.arch.arch),
                   "--include=apt,sudo",
                   self.dist.base_source.codename, dir, self.dist.base_source.get_mirror().url],
                  run_as_root=True)

        # STILL SUDOERS WORKAROUND (remove all when fixed)
        with tempfile.NamedTemporaryFile() as ts:
            ts.write("""
{u} ALL=(ALL) ALL
{u} ALL=NOPASSWD: ALL
""".format(u=pwd.getpwuid(os.getuid())[0]))
            ts.flush()
            misc.call(["cp", ts.name, "{m}/etc/sudoers".format(m=dir)], run_as_root=True)
        # END SUDOERS WORKAROUND

    def prepare(self):
        misc.mkdirs(self.get_path())
        self.get_backend().prepare()

        conf_file = os.path.join(self.get_path(), "schroot.conf")
        open(conf_file, 'w').write("""
[{n}]
description=Mini-Buildd chroot {n}
groups=sbuild
users=mini-buildd
root-groups=sbuild
root-users=mini-buildd
source-root-users=mini-buildd
personality={p}

# Backend specific config
{b}
""".format(n=self.get_name(), p=self.get_personality(), b=self.get_backend().get_schroot_conf()))

        schroot_conf_file = os.path.join("/etc/schroot/chroot.d", self.get_name() + ".conf")
        misc.run_cmd("sudo cp '{s}' '{d}'".format(s=conf_file, d=schroot_conf_file))

    def purge(self):
        self.get_backend().purge()


class FileChroot(Chroot):
    """ File chroot backend. """

    TAR_SUFFIX = (('tar',     "Tar only, don't pack"),
                  ('tar.gz',  "Tar and gzip"),
                  ('tar.bz2', "Tar and bzip2"),
                  ('tar.xz',  "Tar and xz"))
    tar_suffix = django.db.models.CharField(max_length=10, choices=TAR_SUFFIX, default="tar")

    def get_tar_file(self):
        return os.path.join(self.get_path(), "source." + self.tar_suffix)

    def get_tar_compression_opts(self):
        if self.tar_suffix == "tar.gz":
            return ["--gzip"]
        if self.tar_suffix == "tar.bz2":
            return ["--bzip2"]
        if self.tar_suffix == "tar.xz":
            return ["--xz"]
        return []

    def get_schroot_conf(self):
        return """\
type=file
file={t}
""".format(t=self.get_tar_file())

    def prepare(self):
        if not os.path.exists(self.get_tar_file()):
            chroot_dir = self.get_tmp_dir()
            self.debootstrap(dir=chroot_dir)
            misc.call(["tar",
                       "--create",
                       "--directory={d}".format(d=chroot_dir),
                       "--file={f}".format(f=self.get_tar_file()) ] +
                      self.get_tar_compression_opts() +
                      ["."],
                      run_as_root=True)
            misc.call(["rm", "-r", "-f", chroot_dir], run_as_root=True)

    def purge(self):
        ".. todo:: STUB"
        log.error("{i}: STUB only".format(i=self))


class LVMLoopChroot(Chroot):
    """ This class provides some interesting LVM-(loop-)device stuff. """
    filesystem = django.db.models.CharField(max_length=10, default="ext2")
    loop_size = django.db.models.IntegerField(default=100,
                                              help_text="Loop device file size in GB.")

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

    def get_schroot_conf(self):
        return """\
type=lvm-snapshot
device={d}
mount-options=-t {f} -o noatime,user_xattr
lvm-snapshot-options=--size 4G
""".format(d=self.get_lvm_device(), f=self.filesystem)

    def prepare(self):
        # Check image file
        if not os.path.exists(self.get_backing_file()):
            misc.run_cmd("dd if=/dev/zero of='{imgfile}' bs='{gigs}M' seek=1024 count=0".format(\
                    imgfile=self.get_backing_file(), gigs=self.loop_size))
            log.debug("LVMLoop: Image file created: '{b}' size {s}G".format(b=self.get_backing_file(), s=self.loop_size))

        # Check loop dev
        if self.get_loop_device() == None:
            misc.run_cmd("sudo losetup -v -f {img}".format(img=self.get_backing_file()))
            log.debug("LVMLoop {d}@{b}: Loop device attached".format(d=self.get_loop_device(), b=self.get_backing_file()))

        # Check lvm
        try:
            misc.run_cmd("sudo vgchange --available y {vgname}".format(vgname=self.get_vgname()))
        except:
            log.debug("LVMLoop {d}@{b}: Creating new LVM '{v}'".format(d=self.get_loop_device(), b=self.get_backing_file(), v=self.get_vgname()))
            misc.run_cmd("sudo pvcreate -v '{dev}'".format(dev=self.get_loop_device()))
            misc.run_cmd("sudo vgcreate -v '{vgname}' '{dev}'".format(vgname=self.get_vgname(), dev=self.get_loop_device()))

        log.info("LVMLoop prepared: {d}@{b} on {v}".format(d=self.get_loop_device(), b=self.get_backing_file(), v=self.get_vgname()))

        device = "/dev/{v}/{n}".format(v=self.get_vgname(), n=self.get_name())

        try:
            misc.run_cmd("sudo lvdisplay | grep -q '{c}'".format(c=self.get_name()))
            log.info("LV {c} exists, leaving alone".format(c=self.get_name()))
        except:
            log.info("Setting up LV {c}...".format(c=self.get_name()))

            mount_point = self.get_tmp_dir()
            try:
                misc.run_cmd("sudo lvcreate -L 4G -n '{n}' '{v}'".format(n=self.get_name(), v=self.get_vgname()))
                misc.run_cmd("sudo mkfs.{f} '{d}'".format(f=self.filesystem, d=device))
                misc.run_cmd("sudo mount -v -t{f} '{d}' '{m}'".format(f=self.filesystem, d=device, m=mount_point))

                self.debootstrap(dir=mount_point)
                misc.run_cmd("sudo umount -v '{m}'".format(m=mount_point))
                log.info("LV {n} created successfully...".format(n=self.get_name()))
            except:
                log.error("LV {n} creation FAILED. Rewinding...".format(n=self.get_name()))
                try:
                    misc.run_cmd("sudo umount -v '{m}'".format(m=mount_point))
                    misc.run_cmd("sudo lvremove --force '{d}'".format(d=device))
                except:
                    log.error("LV {n} rewinding FAILED.".format(n=self.get_name()))
                raise

    def purge(self):
        try:
            misc.run_cmd("sudo lvremove --force {v}".format(v=self.get_vgname()))
            misc.run_cmd("sudo vgremove --force {v}".format(v=self.get_vgname()))
            misc.run_cmd("sudo pvremove {v}".format(v=self.get_vgname()))
            misc.run_cmd("sudo losetup -d {d}".format(d=self.get_lvm_device()))
            misc.run_cmd("rm -f -v '{f}'".format(f=self.get_backing_file()))
        except:
            log.warn("LVM {n}: Some purging steps may have failed".format(n=self.get_vgname()))
