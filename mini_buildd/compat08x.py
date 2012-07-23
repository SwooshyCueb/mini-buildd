# -*- coding: utf-8 -*-
import imp
import os
import logging

LOG = logging.getLogger(__name__)


def import_conf(conf_file=os.getenv('HOME') + '/.mini-buildd.conf'):
    import mini_buildd.models

    LOG.info("Importing 0.8.x config from: {f}".format(f=conf_file))
    conf08x = imp.load_source('mini_buildd.shconf', conf_file)

    def try_import(func):
        try:
            o = func()
            o.save()
            LOG.info("IMPORTED '{f}': '{n}'".format(f=func.__name__, n=o.__unicode__()))
        except Exception as e:
            LOG.warn("{f}: import failed: {e}".format(f=func.__name__, e=str(e)))

    try_import(mini_buildd.models.create_default_layout)

    # Wander all dists...
    for d in conf08x.mbd_dists.split(", "):
        for t in ["base", "extra"]:
            archs = conf08x.mbd_archs.split(", ")

            a = None
            for a in archs:

                def architecture():
                    return mini_buildd.models.Architecture(arch=a)

                try_import(architecture)

            archs.append("any")
            for a in archs:
                v = "mbd_src_" + d + "_" + t + "_" + a
                sources = getattr(conf08x, v)
                LOG.debug("Pondering source line: {v}={sources}".format(v=v, sources=sources))

                if sources:
                    for value in sources.split(","):
                        # Parsing source line
                        url = value.split(" ")[0]

                        codename = value.split(" ")[1]

                        slist = value.split(";")
                        pin = slist[1] if len(slist) > 1 else ""
                        priority = slist[2] if len(slist) > 2 else "1"

                        # Do some magic to find "origin", not configured explicitly in 0.8.x config
                        origin = "No known origin (0.8.x 'extra source' import)"
                        if (t == "base"):
                            # Base: We assume that 0.8.x used Debian base sources only
                            origin = "Debian"
                        elif "o=" in pin:
                            # Maybe we find an origin id in the apt pin
                            origin = pin.split("o=")[1]
                        elif codename == d + "-backports":
                            # codename from apt line seems to be dist-backports; assuming Debian Backports
                            origin = "Debian Backports"

                        # "Archive"
                        def archive():
                            return mini_buildd.models.Archive(url=url)
                        try_import(archive)

                        # "Source"
                        def source():
                            no = mini_buildd.models.Source(codename=codename, origin=origin)
                            no.save()
                            no.archives = mini_buildd.models.Archive.objects.filter(url=url)
                            return no
                        try_import(source)

                        if (t == "extra"):

                            def prioritysource():
                                ps = mini_buildd.models.PrioritySource(
                                    source=mini_buildd.models.Source.objects.get(codename=codename, origin=origin), priority=priority)
                                ps.save()
                                # Add it to dist
                                dist = mini_buildd.models.Distribution.objects.get(
                                    base_source=mini_buildd.models.Source.objects.get(codename=d, origin="Debian"))
                                dist.extra_sources.add(ps)
                                dist.save()
                                return ps
                            try_import(prioritysource)

                        if (t == "base"):

                            def distribution():
                                return mini_buildd.models.Distribution(base_source=mini_buildd.models.Source.objects.get(codename=d, origin="Debian"))
                            try_import(distribution)

    def repository():
        r = mini_buildd.models.Repository(identity=conf08x.mbd_id, host=conf08x.mbd_rephost,
                                          layout=mini_buildd.models.Layout.objects.get(name="Default"),
                                          apt_allow_unauthenticated=conf08x.mbd_apt_allow_unauthenticated == "true",
                                          mail=conf08x.mbd_mail,
                                          external_home_url=conf08x.mbd_extdocurl)

        for d in mini_buildd.models.Distribution.objects.all():
            r.distributions.add(d)

        for a in mini_buildd.models.Architecture.objects.all():
            r.mandatory_architectures.add(a)
        return r
    try_import(repository)
