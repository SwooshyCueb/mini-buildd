# -*- coding: utf-8 -*-
import os, logging

import django.conf, django.core.handlers.wsgi, django.core.management

from mini_buildd import globals, misc, compat08x

log = logging.getLogger(__name__)

class WebApp(django.core.handlers.wsgi.WSGIHandler):
    """
    This class represents mini-buildd's web application.

    .. todo:: Django settings open questions

       - SITE_ID: ??? Seems this is needed for admin/doc.
       - SECRET_KEY: ??? wtf?
    """

    def __init__(self, home, instdir):
        ".. todo:: Maybe useful later when we fix up static files."
        if int(django.VERSION[1]) >= 4:
            static_admin_dir = "/usr/share/pyshared/django/contrib/admin/static/"
        else:
            static_admin_dir = "/usr/share/pyshared/django/contrib/admin/media/"

        log.info("Configuring && generating django app...")
        super(WebApp, self).__init__()
        self._instdir = instdir

        django.conf.settings.configure(
            DEBUG = globals.DEBUG,
            TEMPLATE_DEBUG = globals.DEBUG,

            SITE_ID = 1,

            DATABASES =
            {
                'default':
                    {
                    'ENGINE': 'django.db.backends.sqlite3',
                    'NAME': os.path.join(home, "config.sqlite"),
                    }
                },
            TIME_ZONE = None,
            USE_L10N = True,
            SECRET_KEY = ")-%wqspscru#-9rl6u0sbbd*yn@$=ic^)-9c$+@@w898co2!7^",
            ROOT_URLCONF = 'mini_buildd.root_urls',
            STATIC_URL = "/static/",
            STATICFILES_DIRS = ( static_admin_dir, ),
            INSTALLED_APPS = (
                'django.contrib.auth',
                'django.contrib.contenttypes',
                'django.contrib.admin',
                'django.contrib.sessions',
                'django.contrib.admindocs',
                'django.contrib.staticfiles',
                'django_extensions',
                'mini_buildd'
                ))
        self.syncdb()

    def set_admin_password(self, password):
        """
        This method sets the password for the administrator.

        :param password: The password to use.
        :type password: string
        """

        import django.contrib.auth.models
        try:
            user = django.contrib.auth.models.User.objects.get(username='admin')
            log.info("Updating 'admin' user password...")
            user.set_password(password)
            user.save()
        except django.contrib.auth.models.User.DoesNotExist:
            log.info("Creating initial 'admin' user...")
            django.contrib.auth.models.User.objects.create_superuser('admin', 'root@localhost', password)

    def create_default_config(self, mirror):
        from mini_buildd import models
        codename = misc.call(["lsb_release", "--short", "--codename"], value_on_error="sid").strip()
        arch = misc.call(["dpkg", "--print-architecture"], value_on_error="i386").strip()

        log.info("Creating default config: {c}:{a} from '{m}'".format(c=codename, a=arch, m=mirror))
        m=models.Mirror(url=mirror)
        m.save()

        s=models.Source(codename=codename)
        s.save()
        s.mirrors.add(m)
        s.save()

        d=models.Distribution(base_source=s)
        d.save()

        a=models.Architecture(arch=arch)
        a.save()

        l=models.Layout(name="Default")
        l.save()
        e=models.Suite(name="experimental", mandatory_version="~{rid}{nbv}+0")
        e.save()
        l.suites.add(e)

        u=models.Suite(name="unstable")
        u.save()
        l.suites.add(u)

        t=models.Suite(name="testing", migrates_from=u)
        t.save()
        l.suites.add(t)

        s=models.Suite(name="stable", migrates_from=t)
        s.save()
        l.suites.add(s)
        l.save()

        r=models.Repository(layout=l, arch_all=a)
        r.save()
        r.archs.add(a)
        r.dists.add(d)
        r.save()

        DefaultChrootClass = models.FileChroot
        #DefaultChrootClass = models.LoopLVMChroot
        c=DefaultChrootClass(dist=d, arch=a)
        c.save()

        b=models.Builder()
        b.save()

        d=models.Dispatcher()
        d.save()

    def syncdb(self):
        log.info("Syncing database...")
        django.core.management.call_command('syncdb', interactive=False, verbosity=0)

    def collectstatic(self):
        ".. todo:: Maybe useful later when we fix up static files."
        log.info("Collecting static data...")
        django.core.management.call_command('collectstatic', interactive=False, verbosity=2)

    def loaddata(self, f):
        if os.path.splitext(f)[1] == ".conf":
            log.info("Try loading ad 08x.conf: {f}".format(f=f))
            compat08x.importConf(f)
        else:
            prefix = "" if f[0] == "/" else self._instdir + "/mini_buildd/fixtures/"
            django.core.management.call_command('loaddata', prefix  + f)

    def dumpdata(self, a):
        log.info("Dumping data for: {a}".format(a=a))
        if a == "08x":
            compat08x.exportConf("/dev/stdout")
        else:
            django.core.management.call_command('dumpdata', a, indent=2, format='json')
