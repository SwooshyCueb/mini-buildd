##########
Quickstart
##########

.. note:: It's recommended to read this Quickstart on the
          mini-buildd instance in question itself, else some of
          the links here will not work as-is.

As a convention, we write code you should run as ``root`` like::

	# apt-get install FOO

and code you should run as ``user`` like::

	? mini-buildd-tool HOST status

In code snippets, names written all-capital (``FOO``, ``HOST``)
are not meant literal but placeholders for customized values.


**************************
Administrator's Quickstart
**************************

**Goal**: Initial fully working setup with the sandbox
repository ``test``.


Install
=======

Prepare to set your admin password when installing, otherwise
just stick to the defaults::

	# apt-get install mini-buildd


Configure
=========

.. note:: In case you are both, **extraordinary hasty and
          adventurous**, you may just run this::

          	? /usr/share/doc/mini-buildd/examples/auto-setup

          This will basically try to run this whole section
          non-interactively, with all defaults. If you really
          just want a quick test-drive, this might be for
          you. **All others should just read on**.

.. note:: Read ``Setup`` below: Run the full ``prepare``,
          ``check`` and ``activate`` treat (ugh!) from model's
          *list view* to make them green.

.. note:: Using the wizards is mostly harmless; calling them is
          idempotent, and they will never touch any existing
          setup.

#. Enter the `web application's configuration section
   </admin/mini_buildd/>`_ and login as superuser ``admin``.

#. Setup **the Daemon** (-> :ref:`Manual <admin_daemon>`).
	#. Edit the one Daemon instance. Get the ``identity`` and the ``gnupg template`` right, changing these later will call for trouble.
	#. ``Setup`` the Daemon instance.

	Daemon green? Go on.

	.. note:: Daemon ``prepare`` will generate your instance ID
	          (read: GnuPG key); you may need to generate some
	          **entropy** (install ``haveged`` maybe) on the
	          system if this stalls.

	.. note:: The Daemon ``identity`` will hereafter be referred to as ``ARCHIVE``.

#. Setup **Sources** (-> :ref:`Manual <admin_sources>`).
	#. Call at least one wizard for each: *Archives*, *Sources*, *PrioritySources*.
	#. ``Setup`` all the Sources you want to use.

	All wanted sources green? Go on.

	.. note:: ``Setup`` of Sources will implicitly pull in
	          architectures and components, and also implicitly
	          sets up the apt keys associated to them. Purists
	          may want to re-check them manually.

#. Setup **Repositories** (-> :ref:`Manual <admin_repositories>`).
	#. Call these wizards, in this order: *Layouts:Defaults*, *Distributions:Defaults*, and finally *Repositories:Sandbox*.
	#. ``Setup`` the  sandbox repository ``test``.

	``test`` repository green? Go on.

#. Setup **Chroots** (-> :ref:`Manual <admin_chroots>`).
	#. Call the *DirChroot:Defaults* wizard.
	#. ``Setup`` all the Chroots you want to use.

	All wanted chroots green? Done!

	.. note:: Preparing chroots may take a while; if you cancel the HTTP request in your browser, preparation will continue anyway.


Start and test
==============

#. Enter `web application's home </mini_buildd/>`_ (stay logged-in as ``admin``).
#. **Start** the daemon.
#. **Build keyring packages**.
	 .. note:: Just reload the home page to update the packager and builder status.
#. **Migrate** the **keyring packages** up all staged suites (i.e. ->testing->stable).
	 .. note:: Just show "Last packages", and click on the
             keyring's source package name to get to the
             package's overview where you can migrate (also see
             the User's Quickstart).
#. Optionally **build** the internal test packages.


*****************
User's Quickstart
*****************
**Goal**: Walk through the most important use cases.


"Bootstrap" a system's APT for a mini-buildd archive
====================================================

The resp. archive's *keyring package* includes both, the APT key
as well as a "library" of all sources available (for easy
integration via ``/etc/apt/sources.list.d/``).

However, the *keyring package* also is **in** the archive, so we
need some initial fiddling to get it installed in the first
place.

**1st**, on `mini-buildd's home </mini_buildd/>`_, jump to the
repository overview page (if there are more than one, use the
repository you intend to actually use on the system
later). Select the ``stable`` suite of your base distribution's
(i.e., squeeze, wheezy, jessie,...) APT line, and then::

	# echo "APT_LINE" >/etc/apt/sources.list.d/tmp.list
	# apt-get update
	# apt-get --allow-unauthenticated install ARCHIVE-archive-keyring
	# rm /etc/apt/sources.list.d/tmp.list

.. note:: You may also get the resp. APT line via
					``mini-buildd-tool`` via the ``getsourceslist`` API
					call in case you have it installed already.

.. note:: You may compare the key' fingerprint (``apt-key
					finger``) with the one on `mini-buildd's home
					</mini_buildd/>`_. There might also be other means set
					up by the local administrator to cross-verify the key.

**2nd**, re-add the stable sources.list back in via
"sources.list library", somewhat like::

	# cd /etc/apt/sources.list.d
	# ln -s /usr/share/mini-buildd/sources.list.d/CODENAME_ARCHIVE_REPO_stable.list .
	# apt-get update

Now you can **opt in or out other sources** from the archive
just by *adding or removing symlinks*.

Install the command line tool
=============================
Access API calls from the command line via ``mini-buildd-tool``::

	# apt-get install python-mini-buildd

The remaining Quickstart will just use ``mini-buildd-tool`` as
example, however the API could also just be accessed via the web
interface.


Setup your user account
=======================

A user account may be needed to, for example, create package subscriptions, access restricted API calls, or upload your GnuPG public key.

#. `Register a user account </accounts/register/>`_.
#. `Setup your profile </mini_buildd/accounts/profile/>`_ (package subscriptions, GnuPG key upload).


Setup dput
==========

Install ``dput``, and setup your ``~/.dput.cf``::

	# apt-get install dput
	? mini-buildd-tool HOST getdputconf >>~/.dput.cf


Authorize yourself to do package uploads
========================================

Upload authorization works via a GnuPG ``allowed`` keyring.

As this depends on the setup of the mini-buildd instance and/or
repository your are using, this cannot be answered generically.

You will be able to upload to a repository when

* your user account profile has your GnuPG key uploaded, and
  your account was approved and enabled for the repository.
* your key is included in the per-repository predefined GnuPG
  keyrings.
* the repository you upload for has authorization disabled
  completely (like in the sandbox repository ``test``).


Upload packages to mini-buildd
==============================

Just like always, via ``dput``. For the default configuration
you get via ``getdputconf`` it's something like::

	? dput mini-buildd-ARCHIVE FOO.changes


Control your package build results
==================================

* Per notify (read: Email): A notification mail is sent to
	* *the uploader* (unless the repository is not configured to
	  do so, or the mail address does not match the allowed list),
	* *any subscriber* or
	* your Email is configured by the administrator to always be
	  notified for that repository.
* Per web on `mini-buildd's home </mini_buildd/>`_: You will
  always find the packages currently being build displayed here,
  plus a list of the last N packages build, and of course
  appropriate links to build logs, changes, etc.


Manage packages
===============

You can **search** for (binary and source) package names via
`API:list
</mini_buildd/api?command=list&pattern=*-archive-keyring>`_,
using shell-like patterns::

	? mini-buildd-tool HOST list '*-archive-keyring'

You can **view a source package** overview via the `API:show
</mini_buildd/api?command=show&package=ARCHIVE-archive-keyring>`_
call (put in your actual daemon identity)::

	? mini-buildd-tool HOST show ARCHIVE-archive-keyring

You will find more options to manage packages like
``API::migrate``, ``API::remove``, ``API::port`` in this web
page overview.


Porting packages ("automatic no-changes ports")
===============================================

You can automatically port packages already in the repository
(``API::port``) as well as arbitrary external source packages
(``API::portext``).

For **internal ports**, checkout the options you have in the source
package view; for **external ports**, go to `mini-buildd's home
</mini_buildd/>`_ and check the options for the repositories.

.. note:: Internal ports may also be triggered automatically on
          uploads via a 'magic lines' in the Debian changelog,
          see (-> :ref:`Manual <user_upload>`).
