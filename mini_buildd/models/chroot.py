# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import shutil
import glob
import logging

import django.db.models
import django.contrib.admin
import django.contrib.messages

import mini_buildd.setup
import mini_buildd.misc

import mini_buildd.models.base
import mini_buildd.models.source

LOG = logging.getLogger(__name__)


class Chroot(mini_buildd.models.base.StatusModel):
    PERSONALITIES = {'i386': 'linux32'}

    source = django.db.models.ForeignKey(mini_buildd.models.source.Source)
    architecture = django.db.models.ForeignKey(mini_buildd.models.source.Architecture)

    personality = django.db.models.CharField(max_length=50, editable=False, blank=True, default="",
                                             help_text="""\
Schroot 'personality' value (see 'schroot'); for 32bit chroots
running on a 64bit host, this must be 'linux32'.
""")
    personality_override = django.db.models.CharField(max_length=50, blank=True, default="",
                                                      help_text=""""\
Leave empty unless you want to override the automated way (via
an internal mapping). Please report manual overrides so it can
go to the default mapping.
""")

    class Meta(mini_buildd.models.base.StatusModel.Meta):
        unique_together = ("source", "architecture")
        ordering = ["source", "architecture"]

    class Admin(mini_buildd.models.base.StatusModel.Admin):
        search_fields = ["source", "architecture"]
        readonly_fields = ["personality"]

    def __unicode__(self):
        return "{c}/{a} ({s})".format(c=self.source.codename, a=self.architecture.name, s=self.mbd_get_status_display())

    def mbd_get_backend(self):
        try:
            return self.filechroot
        except:
            try:
                return self.lvmchroot.looplvmchroot
            except:
                try:
                    return self.lvmchroot
                except:
                    raise Exception("No chroot backend found")

    def mbd_get_path(self):
        return os.path.join(mini_buildd.setup.CHROOTS_DIR, self.source.codename, self.architecture.name)

    def mbd_get_name(self):
        return "mini-buildd-{d}-{a}".format(d=self.source.codename, a=self.architecture.name)

    def mbd_get_tmp_dir(self):
        d = os.path.join(self.mbd_get_path(), "tmp")
        mini_buildd.misc.mkdirs(d)
        return d

    def mbd_get_schroot_conf_file(self):
        return os.path.join(self.mbd_get_path(), "schroot.conf")

    def mbd_get_system_schroot_conf_file(self):
        return os.path.join("/etc/schroot/chroot.d", self.mbd_get_name() + ".conf")

    def mbd_get_sudoers_workaround_file(self):
        return os.path.join(self.mbd_get_path(), "sudoers_workaround")

    def mbd_get_sequence(self):
        return self.mbd_get_backend().mbd_get_pre_sequence() + [
            (["/usr/sbin/debootstrap", "--variant=buildd", "--arch={a}".format(a=self.architecture.name), "--include=sudo",
              self.source.codename, self.mbd_get_tmp_dir(), self.source.mbd_get_archive().url],
             ["/bin/umount", "-v", self.mbd_get_tmp_dir() + "/proc", self.mbd_get_tmp_dir() + "/sys"]),

            (["/bin/cp", "--verbose", self.mbd_get_sudoers_workaround_file(), "{m}/etc/sudoers".format(m=self.mbd_get_tmp_dir())],
             [])] + self.mbd_get_backend().mbd_get_post_sequence() + [

            (["/bin/cp", "--verbose", self.mbd_get_schroot_conf_file(), self.mbd_get_system_schroot_conf_file()],
             ["/bin/rm", "--verbose", self.mbd_get_system_schroot_conf_file()])]

    def mbd_prepare(self, request):
        """
        .. note:: SUDO WORKAROUND for http://bugs.debian.org/cgi-bin/bugreport.cgi?bug=608840

            Includes '--include=sudo' and all handling of 'sudoers_workaround_file' below.

            .. seealso:: :py:class:`~mini_buildd.builder.Build`

        .. todo:: debootstrap rollback fix.
        """
        mini_buildd.misc.mkdirs(os.path.join(self.mbd_get_path(), mini_buildd.setup.CHROOT_LIBDIR))

        # Set personality
        self.personality = ""
        if self.personality_override:
            self.personality = self.personality_override
        else:
            try:
                self.personality = self.PERSONALITIES[self.architecture.name]
            except:
                self.personality = "linux"

        mini_buildd.misc.ConfFile(
            self.mbd_get_sudoers_workaround_file(),
            """\
{u} ALL=(ALL) ALL
{u} ALL=NOPASSWD: ALL
""".format(u=os.getenv("USER"))).save()

        mini_buildd.misc.ConfFile(
            self.mbd_get_schroot_conf_file(),
            """\
[{n}]
description=Mini-Buildd chroot {n}
setup.fstab=mini-buildd/fstab
groups=sbuild
users=mini-buildd
root-groups=sbuild
root-users=mini-buildd
source-root-users=mini-buildd
personality={p}

# Backend specific config
{b}
""".format(n=self.mbd_get_name(), p=self.personality, b=self.mbd_get_backend().mbd_get_schroot_conf())).save()

        mini_buildd.misc.call_sequence(self.mbd_get_sequence(), run_as_root=True)
        self.mbd_msg_info(request, "Chroot {c}: Prepared on system for schroot.".format(c=self))

    def mbd_unprepare(self, request):
        mini_buildd.misc.call_sequence(self.mbd_get_sequence(), rollback_only=True, run_as_root=True)
        shutil.rmtree(self.mbd_get_path())
        self.mbd_msg_info(request, "Chroot {c}: Removed from system.".format(c=self))

    def mbd_check(self, request):
        mini_buildd.misc.call(["/usr/bin/schroot", "--chroot={c}".format(c=self.mbd_get_name()), "--info"])
        self.mbd_msg_info(request, "Chroot {c}: 'schroot --info' works fine.".format(c=self))

    def mbd_get_status_dependencies(self):
        return [self.source]


class FileChroot(Chroot):
    """ File chroot backend. """

    COMPRESSION_NONE = 0
    COMPRESSION_GZIP = 1
    COMPRESSION_BZIP2 = 2
    COMPRESSION_XZ = 3
    COMPRESSION_CHOICES = (
        (COMPRESSION_NONE, "no compression"),
        (COMPRESSION_GZIP, "gzip"),
        (COMPRESSION_BZIP2, "bzip2"),
        (COMPRESSION_XZ, "xz"))

    compression = django.db.models.IntegerField(choices=COMPRESSION_CHOICES, default=COMPRESSION_NONE)

    TAR_ARGS = {
        COMPRESSION_NONE: [],
        COMPRESSION_GZIP: ["--gzip"],
        COMPRESSION_BZIP2: ["--bzip2"],
        COMPRESSION_XZ: ["--xz"]}
    TAR_SUFFIX = {
        COMPRESSION_NONE: "tar",
        COMPRESSION_GZIP: "tar.gz",
        COMPRESSION_BZIP2: "tar.bz2",
        COMPRESSION_XZ: "tar.xz"}

    class Meta(Chroot.Meta):
        pass

    def mbd_get_tar_file(self):
        return os.path.join(self.mbd_get_path(), "source." + self.TAR_SUFFIX[self.compression])

    def mbd_get_schroot_conf(self):
        return """\
type=file
file={t}
""".format(t=self.mbd_get_tar_file())

    def mbd_get_pre_sequence(self):
        LOG.debug("No pre-squence for chroot {c}".format(c=self))
        return []

    def mbd_get_post_sequence(self):
        return [
            (["/bin/tar",
              "--create",
              "--directory={d}".format(d=self.mbd_get_tmp_dir()),
              "--file={f}".format(f=self.mbd_get_tar_file())] +
             self.TAR_ARGS[self.compression] +
             ["."],
             []),
            (["/bin/rm", "--recursive", "--one-file-system", "--force", self.mbd_get_tmp_dir()],
             [])]


class LVMChroot(Chroot):
    """ LVM chroot backend. """
    volume_group = django.db.models.CharField(max_length=80, default="auto",
                                              help_text="Give a pre-existing LVM volume group name. Just leave it on 'auto' for loop lvm chroots.")
    filesystem = django.db.models.CharField(max_length=10, default="ext2")
    snapshot_size = django.db.models.IntegerField(default=4,
                                                  help_text="Snapshot device file size in GB.")

    class Meta(Chroot.Meta):
        pass

    def mbd_get_volume_group(self):
        try:
            return self.looplvmchroot.mbd_get_volume_group()
        except:
            return self.volume_group

    def mbd_get_lvm_device(self):
        return "/dev/{v}/{n}".format(v=self.mbd_get_volume_group(), n=self.mbd_get_name())

    def mbd_get_schroot_conf(self):
        return """\
type=lvm-snapshot
device={d}
mount-options=-t {f} -o noatime,user_xattr
lvm-snapshot-options=--size {s}G
""".format(d=self.mbd_get_lvm_device(), f=self.filesystem, s=self.snapshot_size)

    def mbd_get_pre_sequence(self):
        return [
            (["/sbin/lvcreate", "--size={s}G".format(s=self.snapshot_size), "--name={n}".format(n=self.mbd_get_name()), self.mbd_get_volume_group()],
             ["/sbin/lvremove", "--verbose", "--force", self.mbd_get_lvm_device()]),

            (["/sbin/mkfs.{f}".format(f=self.filesystem), self.mbd_get_lvm_device()],
             []),

            (["/bin/mount", "-v", "-t{f}".format(f=self.filesystem), self.mbd_get_lvm_device(), self.mbd_get_tmp_dir()],
             ["/bin/umount", "-v", self.mbd_get_tmp_dir()])]

    def mbd_get_post_sequence(self):
        return [(["/bin/umount", "-v", self.mbd_get_tmp_dir()], [])]


class LoopLVMChroot(LVMChroot):
    """ Loop LVM chroot backend. """
    loop_size = django.db.models.IntegerField(default=100,
                                              help_text="Loop device file size in GB.")

    class Meta(Chroot.Meta):
        pass

    def mbd_get_volume_group(self):
        return "mini-buildd-loop-{d}-{a}".format(d=self.source.codename, a=self.architecture.name)

    def mbd_get_backing_file(self):
        return os.path.join(self.mbd_get_path(), "lvmloop.image")

    def mbd_get_loop_device(self):
        for f in glob.glob("/sys/block/loop[0-9]*/loop/backing_file"):
            if os.path.realpath(open(f).read().strip()) == os.path.realpath(self.mbd_get_backing_file()):
                return "/dev/" + f.split("/")[3]
        LOG.debug("No existing loop device for {b}, searching for free device".format(b=self.mbd_get_backing_file()))
        return mini_buildd.misc.call(["/sbin/losetup", "--find"], run_as_root=True).rstrip()

    def mbd_get_pre_sequence(self):
        loop_device = self.mbd_get_loop_device()
        LOG.debug("Acting on loop device: {d}".format(d=loop_device))
        return [
            (["/bin/dd",
              "if=/dev/zero", "of={imgfile}".format(imgfile=self.mbd_get_backing_file()),
              "bs={gigs}M".format(gigs=self.loop_size),
              "seek=1024", "count=0"],
             ["/bin/rm", "--verbose", self.mbd_get_backing_file()]),

            (["/sbin/losetup", "--verbose", loop_device, self.mbd_get_backing_file()],
             ["/sbin/losetup", "--verbose", "--detach", loop_device]),

            (["/sbin/pvcreate", "--verbose", loop_device],
             ["/sbin/pvremove", "--verbose", loop_device]),

            (["/sbin/vgcreate", "--verbose", self.mbd_get_volume_group(), loop_device],
             ["/sbin/vgremove", "--verbose", "--force", self.mbd_get_volume_group()])] + super(LoopLVMChroot, self).mbd_get_pre_sequence()
