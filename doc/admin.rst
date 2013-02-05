#####################
Adminstrator's Manual
#####################

************
Introduction
************

************
Installation
************

The mini-buildd user
====================

Logging and Debugging
=====================

.. _admin_configuration:

*************
Configuration
*************

Model statuses
==============

Some of the models have a status attached to it.

This usually refers to a model's associated data on the system
(which can be managed via actions in the configuration
interface):

====================== ================================= ===========================================================
Model                  Associated prepared system data   File location (``~`` denoting mini-buildd's home path)
====================== ================================= ===========================================================
*Daemon*               GnuPG Key                         ``~/.gnupg/``
*Repository*           Reprepro repository               ``~/repositories/REPO_ID/``
*Chroot*               Chroot data and schroot conf      - ``~/var/chroots/CODENAME/ARCH/``
                                                         - ``/etc/schroot/chroot.d/mini-buildd-CODENAME-ARCH.conf``
                                                         - Some backends (like LVM) may taint other system data
====================== ================================= ===========================================================

Some other models also use the same status infrastructure, but
the associated data is prepared internally in the model's data
(sql database) only:

=========================== ==============================================================
Model                       Associated prepared data
=========================== ==============================================================
*AptKey, Uploader, Remote*  Public GnuPG Key
*Source*                    List of matching archives, selected info from Release file
=========================== ==============================================================

Status semantics
----------------

============ ========================== ===============================================================================
Status       Check status               Semantic
============ ========================== ===============================================================================
*Unprepared*                            Aka purged: No associated data.
*Prepared*                              Associated data exists. With no flags, data is checked and in-sync.
                                        Special conditions to the data may apply:
*Prepared*   *Unchecked* (-)            Needs a manual *check* run to set things straight.
*Prepared*   *Changed* (*)              Model was changed, but the date is not yet updated. Needs
                                        a manual *prepare* run to set things straight.
*Prepared*   *Failed* (x)               Check failed.
*Prepared*   *Failed_Reactivate* (A)    Check failed, will be automatically activated again as soon
                                        as *check* succeeds again.
*Active*                                Prepared on the system, checked and activated.
============ ========================== ===============================================================================

Status actions
--------------

Status actions can be called from a model's list view in
django's admin configurator.

=========== ============================================================================
Action      Semantic
=========== ============================================================================
Prepare     Create associated data on the system, or synchronize it with item changes.
Check       Check item and/or associated data.
Activate    Activate the item, or set the auto-activate flag.
Deactivate  Deactivate the item, or remove the auto-activate flag.
Unprepare   Aka purge: Remove all associated data.
=========== ============================================================================

Daemon
======

.. todo:: **FAQ**: *Daemon prepare does not finish.*

	 Increase entropy on the system, either using the physical
	 mouse, keyboard, etc, or alternatively by installing haveged::

		 # apt-get install haveged


Archives and Sources
====================

.. todo:: **FAQ**: *Can't prepare a source as key verification always fails.*

	 You must add **all** keys the Release file is signed with.

	 To make absolutely sure, manually run s.th. like::

		 $ gpg --verify /var/lib/apt/lists/PATH_Release.gpg /var/lib/apt/lists/PATH_Release

	 for the Release in question to get a list of key ids the source
	 is actually signed with.


Suites and Layouts
==================

Distributions and Repositories
==============================

.. todo:: **IDEA**: *Allow pseudo dists "unstable" in changes (aka 'Debian Developer mode').*

	 This would practically mean you could use a dedicated,
	 private mini-buildd repo to upload the very same package
	 designed for a proper Debian upload to mini-buildd first for
	 QA purposes. Maybe there are other uses as well...

	 Currently, we are bound to the triple CODENAME-REPOID-SUITE
	 as distribution in changes files to identify the repo from
	 incoming. A global (i.e., not per repo) additional mapping
	 would be needed, like 'unstable' -> sid-myrepo-sid.

Chroots
=======

.. todo:: **FAQ**: *How to use foreign-architecture chroots with qemu.*

	 Tested with 'armel' (other archs might work as well, but not tested).

	 Install these additional packages::

		 # apt-get install binfmt-support qemu-user-static

	 You will need a version of qemu-user-static with [#debbug683205]_ fixed.

	 In the Chroot configuration, add a line::

		 Debootstrap-Command: /usr/sbin/qemu-debootstrap

	 to the extra options. That's it. Now just prepare && activate as usual.

	 .. rubric:: References:
	 .. [#debbug683205] http://bugs.debian.org/cgi-bin/bugreport.cgi?bug=683205


.. todo:: **FAQ**: *Chroot creating fails due to missing arch in archive (partial mirror).*

	 This might occur, for example, if you use a (local) partial
	 mirror (with debmirror or the like) as mini-buildd archive that
	 does not mirror the arch in question.

	 Atm, all archives you add must provide all architectures you are
	 going to support to avoid problems.

.. todo:: **FAQ**: *sudo fails with "sudo: no tty present and no askpass program specified".*

	 Make sure /etc/sudoers has this line::

		 #includedir /etc/sudoers.d

	 (This is sudo's Debian package's default, but the
	 administrator might have changed it at some point.)

.. todo:: **FEATURE**: *Chroot maintentance (apt-update, fs checks).*

	 [REGR] 0.8.x path: 'lib/chroots-update.d/10_apt-upgrade.hook'.

	 Regular apt-update for source chroots would be nice to have,
	 especially for rolling distribution like unstable/sid or
	 testing.
	 fs checks would only really make sense for lvm chroots.

Uploaders and Remotes
=====================

Provide keyring packages
========================

**************************
Migrate 0.8.x repositories
**************************
