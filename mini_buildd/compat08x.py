# -*- coding: utf-8 -*-
import imp
import time
import os
import logging

import mini_buildd

log = logging.getLogger(__name__)

def importConf(f=os.getenv('HOME') + '/.mini-buildd.conf'):
    """ """
    from mini_buildd import models

    log.info("Importing 0.8.x config from: {f}".format(f=f))
    conf08x = imp.load_source('mini_buildd.shconf', f)

    def tryImport(f):
        try:
            o = f()
            o.save()
            log.info("IMPORTED '{f}': '{n}'".format(f=f.__name__, n=o.__unicode__()))
        except Exception as e:
            log.warn("{f}: import failed: {e}".format(f=f.__name__, e=str(e)))

    tryImport(models.create_default_layout);

    # Wander all dists...
    for d in conf08x.mbd_dists.split(", "):
        for t in ["base", "extra"]:
            archs = conf08x.mbd_archs.split(", ")

            for a in archs:
                v="mbd_bldhost_" + a
                host = getattr(conf08x, v)

                # "Architecture"
                def Architecture():
                    return models.Architecture(arch=a)
                tryImport(Architecture)

                # "Builder"
                def Builder():
                    return models.Builder(host=host, arch=models.Architecture.objects.get(arch=a))
                tryImport(Builder)

            archs.append("any")
            for a in archs:
                v="mbd_src_" + d + "_" + t + "_" + a
                sources = getattr(conf08x, v)
                log.debug("Pondering source line: {v}={sources}".format(v=v, sources=sources))

                if sources:
                    for value in sources.split(","):
                        # Parsing source line
                        mirror = value.split(" ")[0]

                        codename = value.split(" ")[1]

                        slist = value.split(";")
                        pin = slist[1] if len(slist) > 1 else ""
                        prio = slist[2] if len(slist) > 2 else "1"

                        # Do some magic to find "origin", not configured explicitly in 0.8.x config
                        origin="FIXME: No known origin (0.8.x 'extra source' import)"
                        if (t == "base"):
                            # Base: We assume that 0.8.x used Debian base sources only
                            origin = "Debian"
                        elif "o=" in pin:
                            # Maybe we find an origin id in the apt pin
                            origin = pin.split("o=")[1]
                        elif codename == d + "-backports":
                            # codename from apt line seems to be dist-backports; assuming Debian Backports
                            origin="Debian Backports"

                        # "Mirror"
                        def Mirror():
                            return models.Mirror(url=mirror)
                        tryImport(Mirror)

                        # "Source"
                        def Source():
                            no = models.Source(codename=codename, origin=origin)
                            no.save()
                            no.mirrors = models.Mirror.objects.filter(url=mirror)
                            return no
                        tryImport(Source)

                        if (t == "extra"):
                            # "PrioritisedSource"
                            def PrioritisedSource():
                                ps = models.PrioritisedSource(source=models.Source.objects.get(codename=codename, origin=origin), prio=prio)
                                ps.save()
                                # Add it to dist
                                dist = models.Distribution.objects.get(base_source=models.Source.objects.get(codename=d, origin="Debian"))
                                dist.extra_sources.add(ps)
                                dist.save()
                                return ps
                            tryImport(PrioritisedSource)

                        if (t == "base"):
                            # "Distribution"
                            def Distribution():
                                return models.Distribution(base_source=models.Source.objects.get(codename=d, origin="Debian"))
                            tryImport(Distribution)

    def Repository():
        r = models.Repository(id=conf08x.mbd_id, host=conf08x.mbd_rephost,
                              layout=models.Layout.objects.get(name="Default"),
                              apt_allow_unauthenticated=conf08x.mbd_apt_allow_unauthenticated == "true",
                              mail=conf08x.mbd_mail,
                              extdocurl=conf08x.mbd_extdocurl)

        for d in models.Distribution.objects.all():
            r.dists.add(d)

        for a in models.Architecture.objects.all():
            r.archs.add(a)
        return r
    tryImport(Repository);



def exportConf(f=os.getenv('HOME') + "/.mini-buildd.conf.export"):
    """ """
    from mini_buildd import models

    log.info("Exporting 0.8.x config to: {f}".format(f=f))
    f = open(f, 'w')

    f.write("# Created by mini-buildd on {date}\n".format(date=time.strftime("%c")))
    f.write("# coding: utf-8\n")
    r = models.Repository.objects.all()[0]

    f.write('mbd_id="{v}"\n'.format(v=r.id))
    f.write('mbd_rephost="{v}"\n'.format(v=r.host))
    f.write('mbd_httpport="{v}"\n'.format(v=80)) # @todo
    f.write('mbd_sshport="{v}"\n'.format(v=22)) # @todo
    f.write('mbd_mail="{v}"\n'.format(v=r.mail))
    f.write('mbd_extdocurl="{v}"\n'.format(v=r.extdocurl))

    dists = []
    for d in models.Distribution.objects.all():
        dists+=[d.base_source.codename]
    f.write('mbd_dists="{v}"\n'.format(v=", ".join(dists)))

    archs = []
    for a in models.Architecture.objects.all():
        archs+=[a.arch]
    f.write('mbd_archs="{v}"\n'.format(v=", ".join(archs)))

    f.write('mbd_apt_allow_unauthenticated="{v}"\n'.format(v="true" if r.apt_allow_unauthenticated else "false"))
    f.write('mbd_apt_archall="{v}"\n'.format(v=models.Architecture.objects.all()[0].arch))

    for b in models.Builder.objects.all():
        f.write('mbd_bldhost_{a}="{v}"\n'.format(a=b.arch.arch, v=b.host))
        f.write('mbd_deb_build_options_{a}="parallel={v}"\n'.format(a=b.arch.arch, v=b.parallel))

    for d in models.Distribution.objects.all():
        f.write('mbd_src_{d}_base_any="{v}"\n'.format(d=d.base_source.codename, v=d.base_source.get_apt_line()[4:]))
        for a in models.Architecture.objects.all():
            f.write('mbd_src_{d}_base_{a}=""\n'.format(d=d.base_source.codename, a=a.arch))

        v = []
        for e in d.extra_sources.all():
            v += [e.source.get_apt_line()[4:] + ";release o=" + e.source.origin + ";" + str(e.prio)]
        f.write('mbd_src_{d}_extra_any="{v}"\n'.format(d=d.base_source.codename, v=",".join(v)))
        for a in models.Architecture.objects.all():
            f.write('mbd_src_{d}_extra_{a}=""\n'.format(d=d.base_source.codename, a=a.arch))
