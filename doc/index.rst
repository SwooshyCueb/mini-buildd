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
50%    Replace debconf config with django config                      4/6/8             This will allow to migrate most of the scripting to mini-buildd daemon
                                                                                        eventually.
30%    Embed shell code to mini-buildd/python                         3/6/12            After this step, the new infrastructure should basically work (POC),
                                                                                        i.e., one can build packages.
0%     Integrate and test new infrastructure                          6/10/15           Integrate features, bug fixing and fine tuning.
====== ============================================================== ================= ======================================================================


Known Bugs/TODOS
================

 - GnuPG setup: One Master key with subkeys for all repos
 - APT secure: Pub-key per Mirror/Source.
 - chroot: Proper backend support
 - refactor:

   - dispatcher => changes
   - schroot -> chroot
   - model methods

In-code TODOS
=============

.. todolist::


API Reference
=============

.. toctree::
   :maxdepth: 3

   modules


Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
