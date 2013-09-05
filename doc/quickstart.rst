##########
Quickstart
##########

.. note:: It's recommended to read this Quickstart on the mini-buildd instance in question itself, else some of the links here will not work as-is.

As a convention, we write code you should run as ``root`` like::

	# apt-get install xyz

and code you should run as ``user`` like::

	? mini-buildd-tool status

**************************
Administrator's Quickstart
**************************
**Goal**: Initial fully working setup with the sandbox repository ``test``.

Install
=======
Prepare to set your admin password when installing, otherwise
just stick to the defaults::

	# apt-get install mini-buildd

Configure
=========
.. note:: In case you are both, **extraordinary hasty and adventurous**, you may just run this::

						? /usr/share/doc/mini-buildd/examples/auto-setup

					This will basically try to run this whole section
					non-interactively, with all defaults. If you really
					just want a quick test-drive, this might be for
					you. **All others should just read on**.

.. note:: Read ``Setup`` below: Run the full ``prepare``, ``check`` and ``activate`` treat (ugh!) from model's *list view* to make them green.
.. note:: Using the wizards is mostly harmless; calling them is idempotent, and they will never touch any existing setup.

#. Enter the `web application's configuration section </admin/mini_buildd/>`_ and login as superuser ``admin``.

#. Setup **the Daemon** (-> :ref:`Manual <admin_daemon>`).
	 #. Edit the one Daemon instance. Get the ``identity`` and the ``gnupg template`` right, changing these later will call for trouble.
	 #. ``Setup`` the Daemon instance.

	 Daemon green? Go on.

	 .. note:: Daemon ``prepare`` will generate your instance ID (read: GnuPG key); you may need to generate
						 some **entropy** (install ``haveged`` maybe) on the system if this stalls.

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

	 ``test`` repo green? Go on.

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

Install the command line tool
=============================
Access API calls from the command line via ``mini-buildd-tool``::

	# apt-get install python-mini-buildd

Call ``API::status`` once as user to set your default mini-buildd host::

	? mini-buildd-tool --url=http://my.mini-buildd.intra:8066 status

The remaining Quickstart will just use ``mini-buildd-tool`` as
example, however the API could also just be accessed via the web
interface.

Install from mini-buildd repos
==============================
Setup the apt sources on your system somewhat like that::

	# mini-buildd-tool getsourceslist $(lsb_release -s -c) >/etc/apt/sources.list.d/my-mini-buildd.list
	# apt-get update
	# apt-get --allow-unauthenticated install DAEMON_ID-archive-keyring

Setup your user account
=======================
A user account may be needed to, for example, create package subscriptions, access restricted API calls, or upload your GnuPG public key.

#. `Register a user account </accounts/register/>`_.
#. `Setup your profile </mini_buildd/accounts/profile/>`_ (package subscriptions, GnuPG key upload).

Authorize yourself to do package uploads
========================================
Upload authorization works via a GnuPG ``allowed`` keyring.

As this depends on the setup of the mini-buildd instance and/or
repository your are using, this cannot be answered generically.

You will be able to upload to a repository when

* the repository you upload for has auth disabled completely (like in the sandbox repository ``test``).
* your user account profile has your GnuPG key uploaded, and your account was approved and enabled for the repository.
* your key is included in the per-repository predefined GnuPG keyrings.

Upload packages to mini-buildd
==============================
::

	# apt-get install dput
	? mini-buildd-tool getdputconf >>~/.dput.cf
	...
	? dput mini-buildd-DAEMON_ID *.changes

Control your package build results
==================================

* Per notify (read Email). A notification mail is sent to
	* *the uploader* (unless the repo is not configured to do so, or the mail address does not match the allowed list),
	* *any subscriber* or
	* your Email is configured by the administrator to always be notified for that repository.
* Per web on `mini-buildd's home </mini_buildd/>`_
	You will always find the packages currently being build displayed here, plus a list of the last N packages build, and of course
	appropriate links to build logs, changes, etc.

Manage packages
===============
You can **search** for (binary and source) package names via `API:list </mini_buildd/api?command=list&pattern=*-archive-keyring>`_::

	? mini-buildd-tool list '*-archive-keyring'

You can **view a source package** overview via the `API:show </mini_buildd/api?command=show&package=DAEMON_ID-archive-keyring>`_ call (put in your actual daemon identity)::

	? mini-buildd-tool show DAEMON_ID-archive-keyring

There are also find appropriate links to ``API::migrate``, ``API::remove``,
``API::port`` in this web page overview.

You will also find a convenience **external port** link on a
`repository overview </mini_buildd/repositories/test/>`_ web page
to do and external port via ``API::portext``.
