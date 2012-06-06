# -*- coding: utf-8 -*-
import django.contrib.admin

from mini_buildd import models

django.contrib.admin.site.register(models.Mirror, models.Mirror.Admin)
django.contrib.admin.site.register(models.Source, models.Source.Admin)
django.contrib.admin.site.register(models.PrioSource)

django.contrib.admin.site.register(models.Architecture)

django.contrib.admin.site.register(models.Suite)
django.contrib.admin.site.register(models.Layout)
django.contrib.admin.site.register(models.Distribution)
django.contrib.admin.site.register(models.Repository)

django.contrib.admin.site.register(models.Chroot, models.Chroot.Admin)
django.contrib.admin.site.register(models.FileChroot)
django.contrib.admin.site.register(models.LVMChroot)
django.contrib.admin.site.register(models.LoopLVMChroot)

django.contrib.admin.site.register(models.Builder)
django.contrib.admin.site.register(models.Manager)
django.contrib.admin.site.register(models.Remote)
