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

* Integrated http server (webapp and repository delivery).
* Integrated ftp server (incoming).
* Web-based administration.
* Web-based or command line repository maintenance.
* Distributed builders.

*Goodies:*

* Command-based API accessible via web or command line tool.
* Package managing (migration, removal) via API calls.
* Automatic rollback distributions.
* Automatic keyring package generation.
* Automatic ("no-changes") ports of internal or external source packages.
* Package checks, with optional denial on fails.

******************
Technical overview
******************

**mini-buildd** is a Unix daemon written in python. When
running, it provides a http server (per default on port 8066).

The web server serves both, mini-buildd's web application as
well as the package archives.

As soon as a *mini-buildd* instance has been configured to have
an active 'Daemon', it runs an ftp server (per default on port
8067).

The ftp server acts on incoming ``*.changes`` files, both from
users as well as build requests and results from mini-buildd
itself.

Builders (read: active chroots on mini-buildd instances) are
completely generic and interchangeable; distribution specific
build configuration is all carried through the internal
buildrequests. Thus, *mini-buildd* instances may be
interconnected as so-called 'Remotes' to share builders.

.. todo:: **DOC**: *Add top-level overview graphic.*


Simplified packaging workflow
=============================
.. graphviz::

	 digraph flow_simple
	 {
		 subgraph cluster_0
		 {
			 style=filled;
			 color=lightgrey;
			 label="mini-buildd";
			 "Packager";
			 "Repository" [shape=box];
		 }
		 subgraph cluster_1
		 {
			 style=filled;
			 color=lightgrey;
			 label="mini-buildd";
			 "Builder";
			 label = "mini-buildd";
		 }
		 "Developer" -> "Packager" [label="Source package"];
		 "Manager" -> "Repository" [label="Manage"];
		 "Packager" -> "Builder" [label="Request arch0"];
		 "Packager" -> "Builder" [label="Request arch1"];
		 "Builder" -> "Packager" [label="Result arch0"];
		 "Builder" -> "Packager" [label="Result arch1"];
		 "Packager" -> "Repository" [label="install(arch0, arch1)"];
		 "Repository" -> "User" [label="apt"];
	 }


Used software components
========================

mini-buildd does not re-invent the wheel, it's rather a
sophisticated glue to a number of standard (Debian) or
off-the-shelf software components.

The most prominent parts are:

	- web server: **cherrypy3**.
	- ftp server: **pyftpd**.
	- web application framework: **django**.
	- Debian builds: via **sbuild/schroot** combo with snapshotable chroots.
	- repository manager: **reprepro**.
