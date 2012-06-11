# -*- coding: utf-8 -*-
import os, shutil, re, glob, tempfile, pwd, logging

import django.db.models, django.contrib.admin, django.contrib.messages

from mini_buildd import setup, misc

log = logging.getLogger(__name__)

from mini_buildd.models import StatusModel, msg_info, msg_warn, msg_error

class Chroot(StatusModel):
    PERSONALITIES = { 'i386': 'linux32' }

    from mini_buildd.models import Distribution, Architecture
    dist = django.db.models.ForeignKey(Distribution)
    arch = django.db.models.ForeignKey(Architecture)

    class Meta(StatusModel.Meta):
        unique_together = ("dist", "arch")
        ordering = ["dist", "arch"]

    class Admin(StatusModel.Admin):
        search_fields = StatusModel.Admin.search_fields + ["dist", "arch"]
        readonly_fields = StatusModel.Admin.readonly_fields

    def __unicode__(self):
        return "{s}: {c}/{a}".format(
            s=self.get_status_display(),
            c=self.dist.base_source.codename, a=self.arch.name)

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
        return os.path.join(setup.CHROOTS_DIR, self.dist.base_source.codename, self.arch.name)

    def mbd_get_name(self):
        return "mini-buildd-{d}-{a}".format(d=self.dist.base_source.codename, a=self.arch.name)

    def mbd_get_tmp_dir(self):
        d = os.path.join(self.mbd_get_path(), "tmp")
        misc.mkdirs(d)
        return d

    def mbd_get_schroot_conf_file(self):
        return os.path.join(self.mbd_get_path(), "schroot.conf")

    def mbd_get_system_schroot_conf_file(self):
        return os.path.join("/etc/schroot/chroot.d", self.mbd_get_name() + ".conf")

    def mbd_get_sudoers_workaround_file(self):
        return os.path.join(self.mbd_get_path(), "sudoers_workaround")

    def mbd_get_personality(self):
        """
        On 64bit hosts, 32bit schroots must be configured
        with a *linux32* personality to work.

        .. todo:: Chroot personalities

           - This may be needed for other 32-bit archs, too?
           - We currently assume we build under linux only.
        """
        try:
            return self.PERSONALITIES[self.arch.name]
        except:
            return "linux"

    def mbd_get_sequence(self):
        return self.mbd_get_backend().mbd_get_pre_sequence() + [
            (["/usr/sbin/debootstrap", "--variant=buildd", "--arch={a}".format(a=self.arch.name), "--include=apt,sudo",
              self.dist.base_source.codename, self.mbd_get_tmp_dir(), self.dist.base_source.mbd_get_mirror().url],
             ["/bin/umount", "-v", self.mbd_get_tmp_dir() + "/proc", self.mbd_get_tmp_dir() + "/sys"]),

            (["/bin/cp", "--verbose", self.mbd_get_sudoers_workaround_file(), "{m}/etc/sudoers".format(m=self.mbd_get_tmp_dir())],
             [])] + self.mbd_get_backend().mbd_get_post_sequence() + [

            (["/bin/cp", "--verbose", self.mbd_get_schroot_conf_file(), self.mbd_get_system_schroot_conf_file()],
             ["/bin/rm", "--verbose", self.mbd_get_system_schroot_conf_file()])]

    def mbd_prepare(self, request):
        """
        .. todo:: debootstrap

          - mbdAptEnv ??
          - SUDOERS WORKAROUND for http://bugs.debian.org/cgi-bin/bugreport.cgi?bug=608840
            - '--include=sudo' and all handling of 'sudoers_workaround_file'
          - debootstrap include=apt WTF?
        """
        from mini_buildd.models import msg_info
        if self.status >= self.STATUS_PREPARED:
            msg_info(request, "Already prepared: {c}".format(c=self))
            return self.status
        else:
            msg_info(request, "Preparing {c}: This may take a while...".format(c=self))
            misc.mkdirs(self.mbd_get_path())

            open(self.mbd_get_sudoers_workaround_file(), 'w').write("""
{u} ALL=(ALL) ALL
{u} ALL=NOPASSWD: ALL
""".format(u=pwd.getpwuid(os.getuid())[0]))

            open(self.mbd_get_schroot_conf_file(), 'w').write("""
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
""".format(n=self.mbd_get_name(), p=self.mbd_get_personality(), b=self.mbd_get_backend().mbd_get_schroot_conf()))

            misc.call_sequence(self.mbd_get_sequence(), run_as_root=True)
            return self.STATUS_PREPARED

    def mbd_remove(self, request):
        from mini_buildd.models import msg_info
        misc.call_sequence(self.mbd_get_sequence(), rollback_only=True, run_as_root=True)
        shutil.rmtree(self.mbd_get_path())
        msg_info(request, "Removed from system: {c}".format(c=self))
        return self.STATUS_REMOVED

    def mbd_remove(self, request):
        self.mirrors = []
        self.description = ""
        return self.STATUS_REMOVED

    def mbd_activate(self, request):
        status = self.mbd_prepare(request)
        if status >= self.STATUS_PREPARED:
            return self.STATUS_ACTIVE
        else:
            return status

    def mbd_deactivate(self, request):
        if self.status >= self.STATUS_ACTIVE:
            return self.STATUS_PREPARED
        else:
            return self.status

django.contrib.admin.site.register(Chroot, Chroot.Admin)


class FileChroot(Chroot):
    """ File chroot backend. """

    TAR_SUFFIX = (('tar',     "Tar only, don't pack"),
                  ('tar.gz',  "Tar and gzip"),
                  ('tar.bz2', "Tar and bzip2"),
                  ('tar.xz',  "Tar and xz"))
    tar_suffix = django.db.models.CharField(max_length=10, choices=TAR_SUFFIX, default="tar")

    def mbd_get_tar_file(self):
        return os.path.join(self.mbd_get_path(), "source." + self.tar_suffix)

    def mbd_get_tar_compression_opts(self):
        if self.tar_suffix == "tar.gz":
            return ["--gzip"]
        if self.tar_suffix == "tar.bz2":
            return ["--bzip2"]
        if self.tar_suffix == "tar.xz":
            return ["--xz"]
        return []

    def mbd_get_schroot_conf(self):
        return """\
type=file
file={t}
""".format(t=self.mbd_get_tar_file())

    def mbd_get_pre_sequence(self):
        return []

    def mbd_get_post_sequence(self):
        return [
            (["/bin/tar",
              "--create",
              "--directory={d}".format(d=self.mbd_get_tmp_dir()),
              "--file={f}".format(f=self.mbd_get_tar_file()) ] +
             self.mbd_get_tar_compression_opts() +
             ["."],
             []),
            (["/bin/rm", "--recursive", "--one-file-system", "--force", self.mbd_get_tmp_dir()],
             [])]

django.contrib.admin.site.register(FileChroot, Chroot.Admin)


class LVMChroot(Chroot):
    """ LVM chroot backend. """
    vgname = django.db.models.CharField(max_length=80, default="auto",
                                        help_text="Give a pre-existing LVM volume group name. Just leave it on 'auto' for loop lvm chroots.")
    filesystem = django.db.models.CharField(max_length=10, default="ext2")
    snapshot_size = django.db.models.IntegerField(default=4,
                                                  help_text="Snapshot device file size in GB.")

    def mbd_get_vgname(self):
        try:
            return self.looplvmchroot.mbd_get_vgname()
        except:
            return self.vgname

    def mbd_get_lvm_device(self):
        return "/dev/{v}/{n}".format(v=self.mbd_get_vgname(), n=self.mbd_get_name())

    def mbd_get_schroot_conf(self):
        return """\
type=lvm-snapshot
device={d}
mount-options=-t {f} -o noatime,user_xattr
lvm-snapshot-options=--size {s}G
""".format(d=self.mbd_get_lvm_device(), f=self.filesystem, s=self.snapshot_size)

    def mbd_get_pre_sequence(self):
        return [
            (["/sbin/lvcreate", "--size={s}G".format(s=self.snapshot_size), "--name={n}".format(n=self.mbd_get_name()), self.mbd_get_vgname()],
             ["/sbin/lvremove", "--verbose", "--force", self.mbd_get_lvm_device()]),

            (["/sbin/mkfs.{f}".format(f=self.filesystem), self.mbd_get_lvm_device()],
             []),

            (["/bin/mount", "-v", "-t{f}".format(f=self.filesystem), self.mbd_get_lvm_device(), self.mbd_get_tmp_dir()],
             ["/bin/umount", "-v", self.mbd_get_tmp_dir()])]

    def mbd_get_post_sequence(self):
        return [(["/bin/umount", "-v", self.mbd_get_tmp_dir()], [])]

django.contrib.admin.site.register(LVMChroot, Chroot.Admin)


class LoopLVMChroot(LVMChroot):
    """ Loop LVM chroot backend. """
    loop_size = django.db.models.IntegerField(default=100,
                                              help_text="Loop device file size in GB.")

    def mbd_get_vgname(self):
        return "mini-buildd-loop-{d}-{a}".format(d=self.dist.base_source.codename, a=self.arch.name)

    def mbd_get_backing_file(self):
        return os.path.join(self.mbd_get_path(), "lvmloop.image")

    def mbd_get_loop_device(self):
        for f in glob.glob("/sys/block/loop[0-9]*/loop/backing_file"):
            if os.path.realpath(open(f).read().strip()) == os.path.realpath(self.mbd_get_backing_file()):
                return "/dev/" + f.split("/")[3]
        log.debug("No existing loop device for {b}, searching for free device".format(b=self.mbd_get_backing_file()))
        return misc.call(["/sbin/losetup", "--find"], run_as_root=True).rstrip()

    def mbd_get_pre_sequence(self):
        # todo get_loop_device() must not be dynamic
        loop_device = self.mbd_get_loop_device()
        log.debug("Acting on loop device: {d}".format(d=loop_device))
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

            (["/sbin/vgcreate", "--verbose", self.mbd_get_vgname(), loop_device],
             ["/sbin/vgremove", "--verbose", "--force", self.mbd_get_vgname()])] + super(LoopLVMChroot, self).mbd_get_pre_sequence()

django.contrib.admin.site.register(LoopLVMChroot, Chroot.Admin)
