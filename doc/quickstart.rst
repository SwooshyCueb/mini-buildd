##########
Quickstart
##########

*Note*: It's recommended to read this Quickstart on the
mini-buildd instance itself so you can use the direct links.

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
.. note:: Read ``Setup`` below: Run the full ``prepare``, ``check`` and ``activate`` treat (ugh!) from model's *list view* to make them green.
.. note:: Using the wizards is mostly harmless; calling them is idempotent, and they will never touch any existing setup.

.. role:: green

#. Enter the `web application's configuration section </admin/mini_buildd/>`_ and login as superuser ``admin``.

#. Setup **the Daemon** (-> :ref:`Manual <admin_daemon>`).
	 #. Edit the one Daemon instance. Get the ``identity`` and the ``gnupg template`` right, changing these later will call for trouble.
	 #. ``Setup`` the Daemon instance.

	 Daemon green? Go on.

	 .. note:: Daemon ``prepare`` will generate your instance ID (read: GnuPG key); you may need to generate
						 some **entropy** (install ``haveged`` maybe) on the system if this stalls.

#. Setup **Sources** (-> :ref:`Manual <admin_sources>`).
	 #. Call at least one wizard for each: ``Archives``, ``Sources``, ``PrioritySources``.
	 #. ``Setup`` all the Sources you want to use.

	 All wanted sources green? Go on.

	 .. note:: ``Setup`` of Sources will implicitly pull in
						 architectures and components, and also implicitely
						 sets up the apt keys associated to them. Purists
						 may want to re-check them manually.

#. Setup **Repositories** (-> :ref:`Manual <admin_repositories>`).
	 #. Call these wizards, in this order: *Layouts:Defaults*, *Distributions:Defaults*, and finally *Repositories:Sandbox*.
	 #. ``Setup`` the  sandbox repository ``test``.

	 ``test`` repo green? Go on.

#. Setup **Chroots** (-> :ref:`Manual <admin_chroots>`).
	 #. Call the DirChroot::Defaults wizard.
	 #. ``Setup`` all the Chroots you want to use.

	 All wanted chroots green? Done!

	 .. note:: Preparing chroots may take a while; if you cancel the http request in your browser, preparation will continue anyway.

Start and test
==============

#. Enter `web application's home </mini_buildd/>`_ (stay logged-in as ``admin``).
#. **Start** the daemon.
#. **Build** keyring packages.
	 .. note:: Just reload the home page to update the packager and builder status.
#. **Migrate** the keyring packages up all staged suites (i.e. ->testing->stable).
	 .. note:: Just show "Last packages", and klick on the keyring's source package name to get to the package's overview where you can migrate.
#. Optionally **build** the internal test packages.


*****************
User's Quickstart
*****************

This shows how to quickly set up a working "test" repository on
a **freshly installed** mini-buildd package, using local chroots
only, plus a very rough roundtrip on the basic usage.

10. **Control status** on `mini-buildd's home </mini_buildd/>`_.
11. **Search** packages using "*" as pattern to see all.
12. **Propagate** the new keyring package to \*-testing and \*-stable.


User uploads
============

* Use mini-buildd's `Dput config </mini_buildd/download/dput.cf>`_ to upload packages.
* Upload authorization works via GnuPG signing. To enable user uploads:

   * You may disable auth completely for for the repository.
   * You may add a django user, and configure an Uploader object for him.
   * You may add predefined GnuPG keyrings to the repository.

Using the repository
====================

- Go to the `test repository overview </mini_buildd/repositories/test>`_, and grab the needed apt lines.
- Install the keyring package on your system.
