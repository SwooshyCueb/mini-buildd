# -*- coding: utf-8 -*-
import gnupg


class AptKey(gnupg.AptKey):
    pass


class UserProfile(gnupg.UserProfile):
    pass


class Remote(gnupg.Remote):
    pass


import source


class Archive(source.Archive):
    pass


class Architecture(source.Architecture):
    pass


class Component(source.Component):
    pass


class Source(source.Source):
    pass


class PrioritySource(source.PrioritySource):
    pass


import repository


class EmailAddress(repository.EmailAddress):
    pass


class Suite(repository.Suite):
    pass


class Layout(repository.Layout):
    pass


class Distribution(repository.Distribution):
    pass


class Repository(repository.Repository):
    pass


import chroot


class Chroot(chroot.Chroot):
    pass


class FileChroot(chroot.FileChroot):
    pass


class LVMChroot(chroot.LVMChroot):
    pass


class LoopLVMChroot(chroot.LoopLVMChroot):
    pass


import daemon


class Daemon(daemon.Daemon):
    pass
