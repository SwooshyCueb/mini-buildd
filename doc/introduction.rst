############
Introduction
############

**mini-buildd** is a custom build daemon for *Debian*-based
distributions with *all batteries included*: I.e., it covers
**incoming**, **(distributed) building**, **installing**,
**repository maintenance** and **repository delivery**.

.. _introduction_main_components:

***************
Main Components
***************

mini-buildd does not re-invent the wheel, it's rather a
sophisticated glue written in `python
<http://packages.qa.debian.org/p/python.html>`_ to a number of
standard (Debian) or off-the-shelf software components. The most
prominent parts are:

====================== ===================================================== ===========================================================
Component              Used for                                              Realized with
====================== ===================================================== ===========================================================
**HTTP server**        Web application, repository delivery                  `cherrypy3 <http://packages.qa.debian.org/c/cherrypy3.html>`_
**Web application**    Configuration, package tracking                       `python-django <http://packages.qa.debian.org/p/python-django.html>`_
**FTP server**         Incoming (user uploads, build requests and results)   `python-pyftpdlib <http://packages.qa.debian.org/p/python-pyftpdlib.html>`_
**Packager**           Source package manager, build distribution
**Builder**            Package builds                                        `sbuild <http://packages.qa.debian.org/s/sbuild.html>`_ / `schroot <http://packages.qa.debian.org/s/schroot.html>`_ combo using snapshot-able chroots.
**Repository**         APT package archive                                   `reprepro <http://packages.qa.debian.org/r/reprepro.html>`_
====================== ===================================================== ===========================================================

.. _introduction_features:

********
Features
********

*Core features*:

* Integrated **HTTP server** (webapp and repository delivery).
* Integrated **FTP server** (incoming).
* **Web-based configuration**, with integrated managing of chroots and repositories.
* **Distributed builders**.
* **Web-based** or **command line** repository maintenance via *API* calls.

*Some prominent extras*:

* *mini-buildd-tool*: Use from the command line, write scripts.
* *User management*: Package subscriptions, GPG key management, upload authorization.
* *Package QA*: Internal sanity checks, version enforcing, lintian.
* *Package Tracking*: ``Debian PTS``-like web based source package tracker.
* *No-Changes-Ports*: Automates these ports for internal or external source packages.
* *Rollback handling*: Keeps ``N`` rollbacks for any distribution.
* *Builds keyring packages* automatically.


The :doc:`todo` section may also help you to figure out what
mini-buildd is not, or not yet.

.. _introduction_use_cases:

*****************
Example Use Cases
*****************

* *Sandboxing*: Just setup a default ``test`` (sandbox)  repository:
	* Test-drive mini-buildd. Click schlimm on the WebApp.
	* Checkout what No-Changes-Ports are possible.
	* Add a fake user as admin, and spam a colleague with mini-buildd status mails.
* *Debian User*: Maintain a personal package archive. Publish it to your web space via debmirror.
* *Organization*: Set up an archive for all organizational extra packages, ports, etc.


.. _introduction_overview:

***********************
Basic Mode Of Operation
***********************

**mini-buildd** is a Unix daemon written in python. When
running, it provides a HTTP server (on port ``8066`` by default).

The HTTP server serves both, mini-buildd's web application as
well as the delivery of the package repositories.

The instance is being configured in the configuration section of
the web application.

As soon as a *mini-buildd* instance has been configured to have
an active 'Daemon', you may ``start`` the engine, running an FTP
server (on port ``8067`` by default).

The FTP server acts on incoming ``*.changes`` files, both from
developers and other mini-buildd instances (via special
``buildrequest`` and ``buildresult`` changes).

As soon as an instance of *mini-buildd* has active chroots
configured, it acts as *builder*. Chroots are completely generic
and interchangeable, and identified by *codename* and *arch*
only; distribution-specific build configuration is all carried
through the internal buildrequests. Thus, *mini-buildd*
instances may be interconnected as so-called 'Remotes' to share
builders.

This is a simplified example mini-buildd 'network' with three
mini-buildd instances *ernie*, *grover* and *bert*:

.. graphviz::

	 digraph flow_simple
	 {
		 node [fontname=Arial fontsize=11 shape=diamond style=filled fillcolor=grey];
		 edge [fontname=Helvetica fontsize=8];

		 subgraph cluster_0
		 {
			 style=filled;
			 color=lightgrey;
			 label="ernie";
			 "Ernie-Packager" [label="Packager"];
			 "Ernie-Builder" [label="Builder"];
			 "Ernie-Repositories" [label="Repositories" shape=folder];
		 }
		 "Ernie-Developer" [shape=oval fillcolor=lightgrey];
		 "Ernie-Developer" -> "Ernie-Packager" [label="uploads"];
		 "Ernie-Packager" -> "Ernie-Repositories" [label="installs"];
		 "Ernie-Packager" -> {"Ernie-Builder" "Grover-Builder"} [dir=both label="builds"];
		 "Ernie-Manager" [shape=oval fillcolor=lightgrey];
		 "Ernie-Manager" -> "Ernie-Repositories" [label="manages"];
		 "Ernie-User" [shape=oval fillcolor=lightgrey];
		 "Ernie-Repositories" -> "Ernie-User" [label="apt"];

		 subgraph cluster_1
		 {
			 style=filled;
			 color=lightgrey;
			 label="grover";
			 "Grover-Builder" [label="Builder"];
		 }

		 subgraph cluster_2
		 {
			 style=filled;
			 color=lightgrey;
			 label="bert";
			 "Bert-Packager" [label="Packager"];
			 "Bert-Repositories" [label="Repositories" shape=folder];
		 }
		 "Bert-Developer" [shape=oval fillcolor=lightgrey];
		 "Bert-Developer" -> "Bert-Packager" [label="uploads"];
		 "Bert-Packager" -> "Bert-Repositories" [label="installs"];
		 "Bert-Packager" -> {"Ernie-Builder" "Grover-Builder"} [dir=both label="builds"];
		 "Bert-Manager" [shape=oval fillcolor=lightgrey];
		 "Bert-Manager" -> "Bert-Repositories" [label="manages"];
		 "Bert-User" [shape=oval fillcolor=lightgrey];
		 "Bert-Repositories" -> "Bert-User" [label="apt"];
	 }

* *ernie* has repositories and chroots, and uses himself and *grover* as remote for building.
* *grover* only has chroots, and is used by *ernie* and *bert* for building.
* *bert* only has repositories, and uses *ernie* and *grover* as remotes for building.
