# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import copy
import os
import shutil
import contextlib
import glob
import logging

import django.db.models
import django.contrib.admin
import django.contrib.messages

import mini_buildd.setup
import mini_buildd.misc

import mini_buildd.models.base
import mini_buildd.models.source

from mini_buildd.models.msglog import MsgLog
LOG = logging.getLogger(__name__)


class Chroot(mini_buildd.models.base.StatusModel):
    PERSONALITIES = {'i386': 'linux32'}

    source = django.db.models.ForeignKey(mini_buildd.models.source.Source,
                                         help_text="""\
Base source to create the chroot from; its codename must be 'debootstrapable'.

Examples: "Debian 'squeeze'", "Debian 'wheezy'", "Ubuntu 'hardy'".
""")

    architecture = django.db.models.ForeignKey(mini_buildd.models.source.Architecture,
                                               help_text="""\
Chroot's architecture; using the same arch as the host system
will always work, other architectures may work if supported. An
'amd64' host, for example, will also allow for architecture
'i386'.
""")

    personality = django.db.models.CharField(max_length=50, editable=False, blank=True, default="",
                                             help_text="""\
Schroot 'personality' value (see 'schroot'); for 32bit chroots
running on a 64bit host, this must be 'linux32'.
""")
    personality_override = django.db.models.CharField(max_length=50, blank=True, default="",
                                                      help_text="""\
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
        fieldsets = [
            ("Chroot identity", {"fields": (("source", "architecture"), "personality", "personality_override")}),
            ("Extra options",
             {"classes": ("collapse",),
              "description": """
<b>Supported extra options</b>
<p><tt>Debootstrap-Command: ALT_COMMAND</tt>: Alternate command to run instead of standard debootstrap.</p>
<p>
For example, <tt>Debootstrap-Command: /usr/sbin/qemu-debootstrap</tt> may be used to produce <em>armel</em>
chroots (with <tt>qemu-user-static</tt> installed).
</p>
""",
              "fields": ("extra_options",)})]

        def get_readonly_fields(self, _request, obj=None):
            "Forbid change source/arch on existing chroot (we would loose the path to the associated data)."
            fields = copy.copy(self.readonly_fields)
            if obj:
                fields.append("source")
                fields.append("architecture")
            return fields

        @classmethod
        def mbd_host_architecture(cls):
            return mini_buildd.misc.sose_call(["dpkg", "--print-architecture"]).strip()

        @classmethod
        def _mbd_get_supported_archs(cls, arch):
            "Some archs also natively support other archs."
            arch_map = {"amd64": ["i386"]}
            return [arch] + arch_map.get(arch, [])

        @classmethod
        def _mbd_meta_add_base_sources(cls, chroot_model, msglog):
            "Add chroot objects for all base sources found."
            archs = mini_buildd.models.source.Architecture.mbd_supported_architectures()
            msglog.info("Host supports {archs}".format(archs=" ".join(archs)))

            for s in mini_buildd.models.source.Source.Admin.mbd_filter_active_base_sources():
                for a in mini_buildd.models.source.Architecture.objects.filter(name__regex=r"^({archs})$".format(archs="|".join(archs))):
                    try:
                        extra_options = ""
                        if s.codename in ["lenny", "etch"]:
                            extra_options = "Debootstrap-Command: /usr/sbin/mbd-debootstrap-uname-2.6\n"
                        chroot_model.mbd_get_or_create(msglog, source=s, architecture=a, extra_options=extra_options)
                    except:
                        msglog.info("Another backend already provides {s}/{a}".format(s=s.codename, a=a.name))

    def __unicode__(self):
        return "{o} '{c}:{a}' ({f})".format(o=self.source.origin,
                                            c=self.source.codename,
                                            a=self.architecture.name,
                                            f=self.mbd_get_backend().mbd_backend_flavor())

    def mbd_get_backend(self):
        for cls, sub in {"filechroot": [], "dirchroot": [], "lvmchroot": ["looplvmchroot"]}.items():
            if hasattr(self, cls):
                c = getattr(self, cls)
                for s in sub:
                    if hasattr(c, s):
                        return getattr(c, s)
                return c
        raise Exception("No chroot backend found")

    def mbd_get_path(self):
        return os.path.join(mini_buildd.setup.CHROOTS_DIR, self.source.codename, self.architecture.name)

    def mbd_get_name(self):
        return "mini-buildd-{d}-{a}".format(d=self.source.codename, a=self.architecture.name)

    def mbd_get_tmp_dir(self):
        return os.path.join(self.mbd_get_path(), "tmp")

    def mbd_get_schroot_conf_file(self):
        return os.path.join(self.mbd_get_path(), "schroot.conf")

    def mbd_get_keyring_file(self):
        "Holds all keys from the source to verify the release via debootstrap's --keyring option."
        return os.path.join(self.mbd_get_path(), "keyring.gpg")

    def mbd_get_system_schroot_conf_file(self):
        return os.path.join("/etc/schroot/chroot.d", self.mbd_get_name() + ".conf")

    def mbd_get_pre_sequence(self):
        "Subclasses may implement this to do define an extra preliminary sequence."
        LOG.debug("{c}: No pre-sequence defined.".format(c=self))
        return []

    def mbd_get_sequence(self):
        return [
            (["/bin/mkdir", "--verbose", self.mbd_get_tmp_dir()],
             ["/bin/rm", "--recursive", "--one-file-system", "--force", self.mbd_get_tmp_dir()])] + self.mbd_get_backend().mbd_get_pre_sequence() + [
            ([self.mbd_get_extra_option("Debootstrap-Command", "/usr/sbin/debootstrap"),
              "--variant=buildd",
              "--keyring={k}".format(k=self.mbd_get_keyring_file()),
              "--arch={a}".format(a=self.architecture.name),
              self.source.codename,
              self.mbd_get_tmp_dir(),
              self.source.mbd_get_archive().url],
             ["/bin/umount", "-v", os.path.join(self.mbd_get_tmp_dir(), "proc"), os.path.join(self.mbd_get_tmp_dir(), "sys")])] + self.mbd_get_backend().mbd_get_post_sequence() + [

            (["/bin/cp", "--verbose", self.mbd_get_schroot_conf_file(), self.mbd_get_system_schroot_conf_file()],
             ["/bin/rm", "--verbose", self.mbd_get_system_schroot_conf_file()])]

    def mbd_prepare(self, request):
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

        # Gen keyring file to use with debootstrap
        with contextlib.closing(mini_buildd.gnupg.TmpGnuPG()) as gpg:
            for k in self.source.apt_keys.all():
                gpg.add_pub_key(k.key)
            gpg.export(self.mbd_get_keyring_file())

        mini_buildd.misc.call_sequence(self.mbd_get_sequence(), run_as_root=True)
        MsgLog(LOG, request).info("{c}: Prepared on system for schroot.".format(c=self))

    def mbd_remove(self, request):
        mini_buildd.misc.call_sequence(self.mbd_get_sequence(), rollback_only=True, run_as_root=True)
        shutil.rmtree(self.mbd_get_path(),
                      onerror=lambda f, p, e: MsgLog(LOG, request).warn("{c}: Failure removing data dir '{p}' (ignoring): {e}".format(c=self,
                                                                                                                                      p=self.mbd_get_path(),
                                                                                                                                      e=e)))
        MsgLog(LOG, request).info("{c}: Removed from system.".format(c=self))

    def mbd_sync(self, request):
        self._mbd_remove_and_prepare(request)

    def _mbd_schroot_run(self, args, namespace="chroot", user="root"):
        return mini_buildd.misc.sose_call(["/usr/bin/schroot",
                                           "--chroot={n}:{c}".format(n=namespace, c=self.mbd_get_name()),
                                           "--user={u}".format(u=user)] +
                                          args)

    def mbd_check_sudo_workaround(self, request):
        """
        mini-buildd <= 1.0.4 created chroots with a "sudo workaround" for bug
        https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=607228.

        Suche chroots must be recreated, and no longer used.
        """
        has_sudo_workaround = False
        try:
            self._mbd_schroot_run(["--directory=/", "--", "grep", "^{u}".format(u=os.getenv("USER")), "/etc/sudoers"])
            has_sudo_workaround = True
        except:
            MsgLog(LOG, request).info("{c}: Ok, no sudo workaround found.".format(c=self))

        if has_sudo_workaround:
            raise Exception("Chroot has sudo workaround (created with versions <= 1.0.4): Please run 'Remove' + 'PCA' on this chroot to re-create!")

    def mbd_backend_check(self, request):
        "Subclasses may implement this to do extra backend checks."
        MsgLog(LOG, request).info("{c}: No backend check implemented.".format(c=self))

    def mbd_check(self, request):
        # Check for the old sudo workaround (chroots created by mini-buildd <= 1.0.4)
        self.mbd_check_sudo_workaround(request)

        # Basic function checks
        self._mbd_schroot_run(["--info"])

        # Note: When a schroot command comes back to fast, 'modern desktops' might still be busy
        # scrutinizing the new devices schroot created, making schroot fail when closing
        # them with something like
        # '/var/lib/schroot/mount/mini-buildd-wheezy-amd64-aaba77f3-4cba-423e-b34f-2b2bbb9789e1: device is busy.'
        # making this fail _and_ leave schroot cruft around.
        # Wtf! Hence we now just skip this ls test for now.
        #  self._mbd_schroot_run(["--directory=/", "--", "/bin/ls"])

        # Backend checks
        MsgLog(LOG, request).info("{c}: Running backend check.".format(c=self))
        self.mbd_get_backend().mbd_backend_check(request)

        # "apt update/upgrade" check
        for args, fatal in [(["update"], True),
                            (["--ignore-missing", "dist-upgrade"], True),
                            (["--purge", "autoremove"], False),
                            (["clean"], True)]:
            try:
                MsgLog(LOG, request).info("=> Running: apt-get {args}:".format(args=" ".join(args)))
                MsgLog(LOG, request).log_text(
                    self._mbd_schroot_run(["--directory=/", "--", "/usr/bin/apt-get", "-q", "-o APT::Install-Recommends=false", "--yes"] + args,
                                          namespace="source"))
            except:
                MsgLog(LOG, request).warn("'apt-get {args}' not supported in this chroot.".format(args=" ".join(args)))
                if fatal:
                    raise

    def mbd_get_dependencies(self):
        return [self.source]


class DirChroot(Chroot):
    """ Dir chroot backend. """

    UNION_AUFS = 0
    UNION_OVERLAYFS = 1
    UNION_UNIONFS = 2
    UNION_CHOICES = (
        (UNION_AUFS, "aufs"),
        (UNION_OVERLAYFS, "overlayfs"),
        (UNION_UNIONFS, "unionfs"))
    union_type = django.db.models.IntegerField(choices=UNION_CHOICES, default=UNION_AUFS,
                                               help_text="""\
See 'man 5 schroot.conf'
""")

    class Meta(Chroot.Meta):
        pass

    class Admin(Chroot.Admin):
        fieldsets = Chroot.Admin.fieldsets + [("Dir options", {"fields": ("union_type",)})]

        @classmethod
        def mbd_meta_add_base_sources(cls, msglog):
            cls._mbd_meta_add_base_sources(DirChroot, msglog)

    def mbd_backend_flavor(self):
        return self.get_union_type_display()

    def mbd_get_chroot_dir(self):
        return os.path.join(self.mbd_get_path(), "source")

    def mbd_get_schroot_conf(self):
        return """\
type=directory
directory={d}
union-type={u}
""".format(d=self.mbd_get_chroot_dir(), u=self.get_union_type_display())

    def mbd_get_post_sequence(self):
        return [
            (["/bin/mv",
              "--verbose",
              self.mbd_get_tmp_dir(),
              self.mbd_get_chroot_dir()],
             ["/bin/rm", "--recursive", "--one-file-system", "--force", self.mbd_get_chroot_dir()])]


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

    class Admin(Chroot.Admin):
        fieldsets = Chroot.Admin.fieldsets + [("File options", {"fields": ("compression",)})]

        @classmethod
        def mbd_meta_add_base_sources(cls, msglog):
            cls._mbd_meta_add_base_sources(FileChroot, msglog)

    def mbd_backend_flavor(self):
        return self.TAR_SUFFIX[self.compression]

    def mbd_get_tar_file(self):
        return os.path.join(self.mbd_get_path(), "source." + self.TAR_SUFFIX[self.compression])

    def mbd_get_schroot_conf(self):
        return """\
type=file
file={t}
""".format(t=self.mbd_get_tar_file())

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

    class Admin(Chroot.Admin):
        fieldsets = Chroot.Admin.fieldsets + [("LVM options", {"fields": ("volume_group", "filesystem", "snapshot_size")})]

        @classmethod
        def mbd_meta_add_base_sources(cls, msglog):
            cls._mbd_meta_add_base_sources(LVMChroot, msglog)

    def mbd_backend_flavor(self):
        return "lvm={grp}/{fs}/{size}G".format(grp=self.volume_group, fs=self.filesystem, size=self.snapshot_size)

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

            (["/sbin/mkfs", "-t{f}".format(f=self.filesystem), self.mbd_get_lvm_device()],
             []),

            (["/bin/mount", "-v", "-t{f}".format(f=self.filesystem), self.mbd_get_lvm_device(), self.mbd_get_tmp_dir()],
             ["/bin/umount", "-v", self.mbd_get_tmp_dir()])]

    def mbd_get_post_sequence(self):
        return [(["/bin/umount", "-v", self.mbd_get_tmp_dir()], [])]

    def mbd_backend_check(self, request):
        MsgLog(LOG, request).info("{c}: Running file system check...".format(c=self))
        mini_buildd.misc.call(["/sbin/fsck", "-a", "-t{t}".format(t=self.filesystem), self.mbd_get_lvm_device()],
                              run_as_root=True)


class LoopLVMChroot(LVMChroot):
    """ Loop LVM chroot backend. """
    loop_size = django.db.models.IntegerField(default=100,
                                              help_text="Loop device file size in GB.")

    class Meta(LVMChroot.Meta):
        pass

    class Admin(LVMChroot.Admin):
        fieldsets = LVMChroot.Admin.fieldsets + [("Loop options", {"fields": ("loop_size",)})]

        @classmethod
        def mbd_meta_add_base_sources(cls, msglog):
            cls._mbd_meta_add_base_sources(LoopLVMChroot, msglog)

    def mbd_backend_flavor(self):
        return "{size}G loop: {l}".format(size=self.loop_size,
                                          l=super(LoopLVMChroot, self).mbd_backend_flavor())

    def mbd_get_volume_group(self):
        return "mini-buildd-loop-{d}-{a}".format(d=self.source.codename, a=self.architecture.name)

    def mbd_get_backing_file(self):
        return os.path.join(self.mbd_get_path(), "lvmloop.image")

    def mbd_get_loop_device(self):
        for f in glob.glob("/sys/block/loop[0-9]*/loop/backing_file"):
            if os.path.realpath(mini_buildd.misc.open_utf8(f).read().strip()) == os.path.realpath(self.mbd_get_backing_file()):
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
