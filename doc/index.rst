.. mini-buildd documentation master file, created by
   sphinx-quickstart on Thu May  3 08:26:37 2012.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Mini-buildd
***********

Mini-buildd is an easy-to-configure Debian autobuilder and
repository. Its general notion is that of add-ons for a Debian
base distribution (like etch, lenny, or sid) with an emphasis
on clean builds and package checking.

RoadMap to 1.0
==============

High-level roadmap to mini-buildd 1.0. Should be manually
updated with (at least) every uploaded Debian revision.

====== ============================================================== ================= ======================================================================
Status Desc                                                           Effort Estimation Comments
====== ============================================================== ================= ======================================================================
100%   Dedicated python daemon mini-buildd                            2/3/5             This replaces mini-dinstall incoming daemon.
100%    New default distribution scheme with (manual) staging via      1/2/3
       reprepro.
95%    Use reprepro for repository management                         2/3/5             This replaces mini-dinstall repository management, and finally
                                                                                        obsoletes mini-dinstall.
95%    Integrate web application into mini-buildd (config)            3/6/9             This introduces django and the django admin interface into
                                                                                        mini-buildd. Initial replacement of current static html page.
95%    Replace debconf config with django config                      4/6/8             This will allow to migrate most of the scripting to mini-buildd daemon
                                                                                        eventually.
95%    Embed shell code to mini-buildd/python                         3/6/12            After this step, the new infrastructure should basically work (POC),
                                                                                        i.e., one can build packages.
40%    Django (non-config) web app                                    3/4/7             Minimalistic. Show mini-buildd's status plus package migration.
30%    Integrate and test new infrastructure                          6/9/14            Integrate features, bug fixing and fine tuning.
====== ============================================================== ================= ======================================================================


Known missing features
++++++++++++++++++++++

For 1.0:

 - [FEAT] [100%] Auth via gnupg (user uploads, buildrequests, buildresults).
 - [FEAT] [100%] Support for Remotes.
 - [REGR] [50%] 0.8.x pre-build qa-checks: NEW, ORIG (via reprepro).
 - [FEAT] [30%] WebApp: Add package search and propagation feature.

Optional, maybe 1.2:

 - [REGR] Auto-backports.
 - [REGR] Chroot maintentance (apt-update, fs checks).
 - [DEB ] 0.8.x upgradability (not migration).
 - [FEAT] DB schema upgrade support.
 - [IDEA] Custom hooks (prebuild.d source.changes, preinstall.d/arch.changes, postinstall.d/arch.changes)


In-code TODOS
+++++++++++++

.. todolist::


Quickstart
==========

Administration
++++++++++++++

Enter the web application's `configuration section </admin/mini_buildd/>`_.

1. **Configure** and **prepare** the daemon instance.
2. **Add** archive(s).
3. **Add** source(s) and **activate**.
4. **Add** distribution(s).
5. **Add** at least one repository and **activate**.
6. **Add** chroot(s) and **activate**.
7. **Activate** the daemon.
8. **Generate** keyring packages (as a *first test*; section *repository*).

.. note::
   - *[Un]prepare* and *[de]activate* actions can be called from a model's list view.
   - Adding chroots could take a while -- *stay tuned!*
   - To *try out* mini-buildd, it is recommended to name the repository "test".

Uploading
+++++++++
- Use mini-buildd's `Dput config </mini_buildd/download/dput.cf>`_.
*...to be continued...*

Using the repository
++++++++++++++++++++
*...to be continued...*

Manual
======

.. toctree::
   :maxdepth: 2

The manual is yet to be written.


API Reference
=============

.. figure::  _static/mini_buildd_models.png
   :align:   center

   mini_buildd application model overview.

.. toctree::
   :maxdepth: 3

   modules


Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
