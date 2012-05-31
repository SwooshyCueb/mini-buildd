# -*- coding: utf-8 -*-
import os
import shutil
import re
import glob
import tempfile
import pwd
import logging

import django.db

from mini_buildd import globals, misc

log = logging.getLogger(__name__)

class Chroot(django.db.models.Model):
    PERSONALITIES = { 'i386': 'linux32' }

    from mini_buildd.models import Distribution, Architecture
    dist = django.db.models.ForeignKey(Distribution)
    arch = django.db.models.ForeignKey(Architecture)

    def __unicode__(self):
        return "Chroot: {c}:{a}".format(c=self.dist.base_source.codename, a=self.arch.arch)

    class Meta:
        unique_together = ("dist", "arch")

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

    def get_schroot_conf_file(self):
        return os.path.join(self.get_path(), "schroot.conf")

    def get_system_schroot_conf_file(self):
        return os.path.join("/etc/schroot/chroot.d", self.get_name() + ".conf")

    def get_sudoers_workaround_file(self):
        return os.path.join(self.get_path(), "sudoers_workaround")

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

    def get_sequence(self):
        return self.get_backend().get_pre_sequence() + [
            (["debootstrap", "--variant=buildd", "--arch={a}".format(a=self.arch.arch), "--include=apt,sudo",
              self.dist.base_source.codename, self.get_tmp_dir(), self.dist.base_source.get_mirror().url],
             []),
            (["cp", self.get_sudoers_workaround_file(), "{m}/etc/sudoers".format(m=self.get_tmp_dir())],
             [])] + self.get_backend().get_post_sequence() + [
            (["cp",  self.get_schroot_conf_file(), self.get_system_schroot_conf_file()],
             ["rm", "--verbose", self.get_system_schroot_conf_file()])]

    def is_prepared(self):
        return os.path.exists(self.get_system_schroot_conf_file())

    def prepare(self):
        """
        .. todo:: debootstrap

          - mbdAptEnv ??
          - SUDOERS WORKAROUND for http://bugs.debian.org/cgi-bin/bugreport.cgi?bug=608840
            - '--include=sudo' and all handling of 'sudoers_workaround_file'
          - debootstrap include=apt WTF?
        """
        if self.is_prepared():
            log.info("Already prepared: {c}".format(c=self))
        else:
            misc.mkdirs(self.get_path())

            open(self.get_sudoers_workaround_file(), 'w').write("""
{u} ALL=(ALL) ALL
{u} ALL=NOPASSWD: ALL
""".format(u=pwd.getpwuid(os.getuid())[0]))

            open(self.get_schroot_conf_file(), 'w').write("""
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

            misc.call_sequence(self.get_sequence(), run_as_root=True)

    def purge(self):
        misc.call_sequence(self.get_sequence(), rollback_only=True, run_as_root=True)
        shutil.rmtree(self.get_path())

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

    def get_pre_sequence(self):
        return []

    def get_post_sequence(self):
        return [
            (["tar",
              "--create",
              "--directory={d}".format(d=self.get_tmp_dir()),
              "--file={f}".format(f=self.get_tar_file()) ] +
             self.get_tar_compression_opts() +
             ["."],
             []),
            (["rm", "-r", "-f", self.get_tmp_dir()],
             [])]


class LVMLoopChroot(Chroot):
    """ This class provides some interesting LVM-(loop-)device stuff. """
    filesystem = django.db.models.CharField(max_length=10, default="ext2")
    loop_size = django.db.models.IntegerField(default=100,
                                              help_text="Loop device file size in GB.")
    snapshot_size = django.db.models.IntegerField(default=4,
                                                  help_text="Snapshot device file size in GB.")

    def get_vgname(self):
        return "mini-buildd-loop-{d}-{a}".format(d=self.dist.base_source.codename, a=self.arch.arch)

    def get_backing_file(self):
        return os.path.join(self.get_path(), "lvmloop.image")

    def get_loop_device(self):
        for f in glob.glob("/sys/block/loop[0-9]*/loop/backing_file"):
            if os.path.realpath(open(f).read().strip()) == os.path.realpath(self.get_backing_file()):
                return "/dev/" + f.split("/")[3]

    def get_lvm_device(self):
        return "/dev/{v}/{n}".format(v=self.get_vgname(), n=self.get_name())

    def get_schroot_conf(self):
        return """\
type=lvm-snapshot
device={d}
mount-options=-t {f} -o noatime,user_xattr
lvm-snapshot-options=--size {s}G
""".format(d=self.get_lvm_device(), f=self.filesystem, s=self.snapshot_size)

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

        try:
            misc.run_cmd("sudo lvdisplay | grep -q '{c}'".format(c=self.get_name()))
            log.info("LV {c} exists, leaving alone".format(c=self.get_name()))
        except:
            mount_point = self.get_tmp_dir()
            create_and_mount = [
                (["lvcreate", "--size={s}G".format(s=self.snapshot_size), "--name={n}".format(n=self.get_name()), self.get_vgname()],
                 ["lvremove", "--force", self.get_lvm_device()]),
                (["mkfs.{f}".format(f=self.filesystem), self.get_lvm_device()],
                 ["echo", "No rollback for mkfs"]),
                (["mount", "-v", "-t{f}".format(f=self.filesystem), self.get_lvm_device(), mount_point],
                 ["umount", "-v", mount_point])
                ]
            misc.call_sequence(create_and_mount, run_as_root=True)
            self.debootstrap(dir=mount_point)
            misc.call(["umount", "-v", mount_point], run_as_root=True)

    def purge(self):
        try:
            misc.run_cmd("sudo lvremove --force {v}".format(v=self.get_vgname()))
            misc.run_cmd("sudo vgremove --force {v}".format(v=self.get_vgname()))
            misc.run_cmd("sudo pvremove {v}".format(v=self.get_vgname()))
            misc.run_cmd("sudo losetup -d {d}".format(d=self.get_lvm_device()))
            misc.run_cmd("rm -f -v '{f}'".format(f=self.get_backing_file()))
        except:
            log.warn("LVM {n}: Some purging steps may have failed".format(n=self.get_vgname()))
