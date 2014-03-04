#############
User's Manual
#############

The user's manual covers **using** a mini-buildd installation
-- i.e., everything you can do with it given someone else had
already set it up for you as a service.

************
Introduction
************

The core functionalities of mini-buildd are, 1st the
arch-multiplexed clean building, and 2nd providing a
repository. You don't need to worry about 1st, mini-buildd just
does it for you.

The 2nd however, the repository, goes public and hits "global
Debian namespace"; so, as a big picture, it's important first to
understand how mini-buildd's (default) setup tries to deal with
this.

First of all, each **instance** has it's own **identity**
string, which will be used in the name of the keyring package,
and will also appear in the apt repository in the ``Origin``
field.

Second, each instance instance may have ``N`` **repositories**,
which each have their own **identity** string, which determines
the actual distribution names (``CODENAME-ID-SUITE``) to be used
for uploads or in apt lines.

Both identities should be "globally unique" to avoid any
confusion or conflicts with other existing repositories.

.. note:: Exceptions are the generic *Sandbox* and *Developer*
          repositories, with the de-facto standard names
          ``test`` and ``debdev``; these should never be used
          publicly or for anything but testing.

Third, when people are mixing repositories together, we want to avoid
package clashes, like same PACKAGE-VERSION from two different
repositories. Also, we want guaranteed upgradeability between two
different base distributions, and from experimental to
non-experimental suites. Hence, at least in the **Default
Layout**, we also have a **version restriction**, which
resembles that of Debian Backports:

.. _user_default_layouts:

==================== ========= =================== ========================= ========================= ============================
The Default Layout's Suites and Semantics Overview
-----------------------------------------------------------------------------------------------------------------------------------
Suite                Flags     Version restriction Repository                Semantic                  Consumer
==================== ========= =================== ========================= ========================= ============================
*experimental*       U E 6R    ``~ID+0``           No auto                   *Use at will*             Developer.
snapshot             U E 12R   ``~ID+0``           No auto, but upgrades     *Continuous integration*  Developer, beta tester.
``unstable``         U M 9R    ``~ID+[1-9]``       No auto, but upgrades     *Proposed for live*       Developer, beta tester.
``testing``          M 3R      ``~ID+[1-9]``       No auto, but upgrades     *QA testing*              Quality Assurance.
``stable``           6R        ``~ID+[1-9]``       No auto, but upgrades     *Live*                    End customer.
==================== ========= =================== ========================= ========================= ============================

``U``: Uploadable ``M``: Migrates ``E``: Experimental ``NR``: keeps N Rollback versions ``ID``: repository IDentity

.. _user_setup:

**********
User Setup
**********

As a **minimal setup**, you should have a *web browser installed*;
you can instantly `browse mini-buildd </mini_buildd/>`_, and use
all functionality that do not require extra permissions.

To be able **use advanced functionality** (for example, create
package subscriptions, access restricted API calls, or upload
your GnuPG public key), create a *user account*:

#. `Register a user account </accounts/register/>`_.
#. `Setup your profile </mini_buildd/accounts/profile/>`_ (package subscriptions, GnuPG key upload).

To **access mini-buildd from the command line** via
``mini-buildd-tool``, install ``python-mini-buildd``::

	# apt-get install python-mini-buildd

To **upload packages**, install ``dput`` and add `mini-buildd's
dput config </mini_buildd/api?command=getdputconf>`_ to your
``~/.dput.cf``::

	# apt-get install dput
	? mini-buildd-tool HOST getdputconf >>~/.dput.cf

.. note:: After ``~/.dput.cf`` has been set up this way, you can
          use ``[USER@]ID``-like shortcuts instead of ``HOST``,
          and these will also appear in the bash auto-completion
          of ``mini-buildd-tool``.


.. _user_repository:

********************
Using the repository
********************

.. _user_upload:

****************
Upload a package
****************

Changelog Magic Lines (per-upload control)
==========================================

``mini-buildd`` currently supports these so called ``magic
lines`` as changelog entry to control it on a per-upload basis::

	MINI_BUILDD: BACKPORT_MODE
	  Make QA-Checks that usually break when backporting unlethal (like lintian).

	MINI_BUILDD: AUTO_BACKPORTS: CODENAME-REPOID-SUITE[,CODENAME-REPOID-SUITE...]
	  After successful build for the upload distribution, create and upload automatic internal ports for the given distributions.

.. _user_api:

*************
Using the API
*************

.. _user_ports:

***************
Automatic ports
***************

Internal ports
==============

External ports
==============

.. _user_maintenance:

**********************
Repository maintenance
**********************
.. todo:: **IDEA**: *Dependency check on package migration.*

.. todo:: **IDEA**: *Custom hooks (prebuild.d source.changes, preinstall.d/arch.changes, postinstall.d/arch.changes).*

FAQ
===
.. todo:: **FAQ**: *aptitude GUI does not show distribution or origin of packages*

	 To show the distribution of packages, just add ``%t`` to the
	 package display format [#debbug484011]_::

		 aptitude::UI::Package-Display-Format "%c%a%M%S %p %t %Z %v %V";

	 The origin cannot be shown in the package display format
	 [#debbug248561]_. However, you may change the "default grouping" to
	 categorize with "origin". I prefer this::

		 aptitude::UI::Default-Grouping "task,status,pattern(~S~i~O, ?true ||),pattern(~S~i~A, ?true ||),section(subdirs,passthrough),section(topdir)";

	 setting which will group installed packages in "Origin/Archive"
	 hierarchy.

	 Additionally to aptitude's default "Obsolete and locally
	 installed" top level category (which only shows packages not in
	 any apt archive), this grouping also conveniently shows
	 installed package _versions_ which are not currently in any
	 repository (check "Installed Packages/now").

.. todo:: **BUG**: *apt secure problems after initial (unauthorized) install of the archive-key package*

	 - aptitude always shows <NULL> archive

	 You can verify this problem via::

		 # aptitude -v show YOURID-archive-keyring | grep ^Archive
		 Archive: <NULL>, now

	 - BADSIG when verifying the archive keyring package's signature

	 Both might be variants of [#debbug657561]_ (known to occur
	 for <= squeeze). For both, check if this::

		 # rm -rf /var/lib/apt/lists/*
		 # apt-get update

	 fixes it.

.. todo:: **FAQ**: *Multiple versions of packages in one distribution*

	 This is not really a problem, but a uncommon situation that
	 may lead to confusion.

	 Generally, reprepro does allow exactly only one version of a
	 package in a distribution; the only exception is when
	 installed in *different components* (e.g., main
	 vs. non-free).

	 This usually happens when the 'Section' changes in the
	 corresponding 'debian/control' file of the source package, or
	 if packages were installed manually using "-C" with reprepro.

	 Check with the "show" command if this is the case, i.e., s.th. like::

		 $ mini-buildd-tool show my-package

	 you may see multiple entries for one distribution with different components.

	 mini-buildd handles this gracefully; the ``remove``,
	 ``migrate`` and ``port`` API calls all include an optional
	 'version' parameter to be able to select a specific version.

	 In the automated rollback handling, all versions of a source
	 package are shifted.


**********
References
**********

.. rubric:: References:
.. [#debbug484011] http://bugs.debian.org/cgi-bin/bugreport.cgi?bug=484011
.. [#debbug248561] http://bugs.debian.org/cgi-bin/bugreport.cgi?bug=248561
.. [#debbug657561] http://bugs.debian.org/cgi-bin/bugreport.cgi?bug=657561
