# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import django.db.models
import django.contrib.auth.models

import mini_buildd.models.base


class Subscription(mini_buildd.models.base.Model):
    subscriber = django.db.models.ForeignKey(django.contrib.auth.models.User)
    package = django.db.models.CharField(max_length=100, blank=True)
    distribution = django.db.models.CharField(max_length=100, blank=True)

    def mbd_unicode(self):
        return "{u}: '{p}:{d}'".format(u=self.subscriber, p=self.package, d=self.distribution)
