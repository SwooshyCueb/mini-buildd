############
Introduction
############

**mini-buildd** is a custom build daemon for *Debian*-based
distributions with *all batteries included*: I.e., it covers
**incoming**, **(distributed) building**, **installing**,
**repository maintenance** and **repository delivery**.

.. _features:

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

* *Automated* ("no-changes") *ports* of internal or external source packages.
* *Automatic* handling of *rollback* distributions.
* *Automated keyring package* generation.
* *Package QA* (currently internal checks, version enforcing, lintian).

The :doc:`todo` section may also help you to figure out what
mini-buildd is not, or not yet.

********
Overview
********

**mini-buildd** is a Unix daemon written in python. When
running, it provides a HTTP server (per default on port 8066).

The HTTP server serves both, mini-buildd's web application as
well as the delivery of the package repositories.

The instance is being configured in the configuration section of
the web application.

As soon as a *mini-buildd* instance has been configured to have
an active 'Daemon', it runs an FTP server (per default on port
8067).

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

*******************
Software components
*******************

mini-buildd does not re-invent the wheel, it's rather a
sophisticated glue to a number of standard (Debian) or
off-the-shelf software components.

The most prominent parts are:

* HTTP server: `cherrypy3 <http://packages.qa.debian.org/c/cherrypy3.html>`_.
* FTP server: `python-pyftpdlib <http://packages.qa.debian.org/p/python-pyftpdlib.html>`_.
* Web application framework: `python-django <http://packages.qa.debian.org/p/python-django.html>`_.
* Debian builds: via `sbuild <http://packages.qa.debian.org/s/sbuild.html>`_ / `schroot <http://packages.qa.debian.org/s/schroot.html>`_ combo using snapshot-able chroots.
* Repository manager: `reprepro <http://packages.qa.debian.org/r/reprepro.html>`_.
