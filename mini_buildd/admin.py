from django.contrib import admin
from mini_buildd.models import *

admin.site.register(Mirror, Mirror.Admin)
admin.site.register(Source, Source.Admin)
admin.site.register(PrioritisedSource)

admin.site.register(Architecture)
admin.site.register(Builder)

admin.site.register(Suite)
admin.site.register(Layout)
admin.site.register(Distribution)
admin.site.register(Repository)

# 0.8.x compatibilty
admin.site.register(Import08x)
admin.site.register(Export08x)
