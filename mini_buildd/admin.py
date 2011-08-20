from django.contrib import admin
from mini_buildd.webapp.models import *

admin.site.register(AptLine)
admin.site.register(Distribution)
admin.site.register(Architecture)
admin.site.register(Builder)
admin.site.register(Repository)
