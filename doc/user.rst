#############
User's Manual
#############

.. _user_introduction:

************
Introduction
************

.. _user_setup:

*****************
Setup your system
*****************

.. _user_upload:

****************
Upload a package
****************

.. _user_default_layouts:

*******************************
Semantics of the Default Layout
*******************************
==================== ========= ========================= ============================
Suite                Flags     Semantic                  Consumer
==================== ========= ========================= ============================
*experimental*       U E R6    Use at will               Developer.
snapshot             U E R12   Continuous integration    Developer, beta tester.
``unstable``         U M R9    Proposed for live         Developer, beta tester.
``testing``          M R3      QA testing                Quality Assurance.
``stable``           R6        Live                      End customer.
==================== ========= ========================= ============================

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

.. _user_repository:

********************
Using the repository
********************

FAQ
===
.. todo:: **BUG**: *lintian version from host is used for all distributions*

	 We use sbuild's --run-lintian option, which is currently runs lintian
	 from the host, see [#debbug626361]_.

.. todo:: **FAQ**: *aptitude gui does not show distribution or origin of packages*

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

		 # aptitude -v show YOURID-archive-keyring | grep ^Archiv
		 Archiv: <NULL>, now

	 - BADSIG when verifying the archive keyring package's signature

	 Both might be variants of [#debbug657561]_ (known to occur
	 for <= squeeze). For both, check if this::

		 # rm -rf /var/lib/apt/lists/*
		 # apt-get update

	 fixes it.

.. todo:: **FAQ**: *Multiple versions of a packages in one distribution*

	 This is not really a problem, but a uncommon situation that
	 may lead to confusion.

	 Generally, reprepro does allow exactly only one version of a
	 package in a distribution; the only exception is when
	 installed in *different components* (e.g., main
	 vs. non-free).

	 This usually happens when the 'Section' changes in the
	 corresponding 'debian/control' file of the source package, or
	 if package were installed manually using "-C" with reprepro.

	 Check with the "show" command if this is the case, i.e., s.th. like::

		 $ mini-buildd-tool show my-package

	 you may see multiple entries for one distribution with different components.

	 mini-buildd handles this gracefully; the remove, migrate and
	 port api calls all include an optional 'version' parameter to be
	 able to select a specific version.

	 In the automated rollback handling, all versions of a source
	 package are shifted.

##########
References
##########
.. rubric:: References:
.. [#debbug626361] http://bugs.debian.org/cgi-bin/bugreport.cgi?bug=626361
.. [#debbug484011] http://bugs.debian.org/cgi-bin/bugreport.cgi?bug=484011
.. [#debbug248561] http://bugs.debian.org/cgi-bin/bugreport.cgi?bug=248561
.. [#debbug657561] http://bugs.debian.org/cgi-bin/bugreport.cgi?bug=657561
