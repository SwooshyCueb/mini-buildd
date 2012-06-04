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

Manual
======

.. toctree::
   :maxdepth: 2

The manual is yet to be written.


RoadMap to 1.0
==============

High-level roadmap to mini-buildd 1.0. Should be manually
updated with (at least) every uploaded Debian revision.

====== ============================================================== ================= ======================================================================
Status Desc                                                           Effort Estimation Comments
====== ============================================================== ================= ======================================================================
100%   Dedicated python daemon mini-buildd                            2/3/5             This replaces mini-dinstall incoming daemon.
80%    Use reprepro for repository management                         2/3/5             This replaces mini-dinstall repository management, and finally
                                                                                        obsoletes mini-dinstall.
80%    New default distribution scheme with (manual) staging via      1/2/3
       reprepro.
70%    Integrate web application into mini-buildd (config)            3/6/9             This introduces django and the django admin interface into
                                                                                        mini-buildd. Initial replacement of current static html page.
70%    Replace debconf config with django config                      4/6/8             This will allow to migrate most of the scripting to mini-buildd daemon
                                                                                        eventually.
50%    Embed shell code to mini-buildd/python                         3/6/12            After this step, the new infrastructure should basically work (POC),
                                                                                        i.e., one can build packages.
20%    Django (non-config) web app                                    3/4/7             Minimalistic. Show mini-buildd's status plus package migration.
10%    Integrate and test new infrastructure                          6/9/14            Integrate features, bug fixing and fine tuning.
====== ============================================================== ================= ======================================================================


Buildd engine known missing features
====================================

 - [REGR] Support repo keys && loop through to builders.
 - [REGR] Support preseed && loop through to builders.
 - [FEAT] Complete auth via gnupg.
 - [FEAT] Remotes support.
 - [REGR] Notification support.
 - [REGR] 0.8.x pre-build qa-checks.
 - [REGR] Auto backports.
 - [FEAT] Auto-generated keyring packages.
 - [REFE] Chroot maintentance (apt-update, fs checks)


In-code TODOS
=============

.. todolist::


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
