# -*- coding: utf-8 -*-
import django.contrib
import mini_buildd.models

django.contrib.admin.site.register(mini_buildd.models.Mirror, mini_buildd.models.Mirror.Admin)
django.contrib.admin.site.register(mini_buildd.models.Source, mini_buildd.models.Source.Admin)
django.contrib.admin.site.register(mini_buildd.models.PrioritisedSource)

django.contrib.admin.site.register(mini_buildd.models.Architecture)

django.contrib.admin.site.register(mini_buildd.models.Suite)
django.contrib.admin.site.register(mini_buildd.models.Layout)
django.contrib.admin.site.register(mini_buildd.models.Distribution)
django.contrib.admin.site.register(mini_buildd.models.Repository)

django.contrib.admin.site.register(mini_buildd.models.FileChroot)
django.contrib.admin.site.register(mini_buildd.models.LVMLoopChroot)
django.contrib.admin.site.register(mini_buildd.models.Builder)

django.contrib.admin.site.register(mini_buildd.models.Remote)
