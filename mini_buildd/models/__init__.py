# -*- coding: utf-8 -*-
MODELS = [
    "gnupg.AptKey",
    "gnupg.Uploader",
    "gnupg.Remote",
    "source.Archive",
    "source.Architecture",
    "source.Component",
    "source.Source",
    "source.PrioritySource",
    "repository.EmailAddress",
    "repository.Suite",
    "repository.Layout",
    "repository.Distribution",
    "repository.Repository",
    "chroot.Chroot",
    "chroot.FileChroot",
    "chroot.LVMChroot",
    "chroot.LoopLVMChroot",
    "daemon.Daemon"]


def import_all():
    from mini_buildd.models import gnupg
    from mini_buildd.models import source
    from mini_buildd.models import repository
    from mini_buildd.models import chroot
    from mini_buildd.models import daemon
