# -*- coding: utf-8 -*-
"""
Django modules package.

All models must provide a an admin meta class as 'Model.Admin'.
"""
from __future__ import unicode_literals


def import_all():
    """
    Call this after your django app is configured.
    """
    import django.contrib

    from mini_buildd.models import gnupg
    from mini_buildd.models import source
    from mini_buildd.models import repository
    from mini_buildd.models import chroot
    from mini_buildd.models import daemon

    models = [
        gnupg.AptKey,
        gnupg.Uploader,
        gnupg.Remote,
        source.Archive,
        source.Architecture,
        source.Component,
        source.Source,
        source.PrioritySource,
        repository.EmailAddress,
        repository.Suite,
        repository.Layout,
        repository.Distribution,
        repository.Repository,
        chroot.Chroot,
        chroot.DirChroot,
        chroot.FileChroot,
        chroot.LVMChroot,
        chroot.LoopLVMChroot,
        daemon.Daemon]

    for m in models:
        m_admin = getattr(m, "Admin")
        django.contrib.admin.site.register(m, m_admin)
