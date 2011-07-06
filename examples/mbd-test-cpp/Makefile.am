AUTOMAKE_OPTIONS = 1.10
ACLOCAL_AMFLAGS =

SUBDIRS = src

EXTRA_DIST = .ui-auto.conf

docdir = $(datadir)/doc/$(PACKAGE)
doc_DATA = README NEWS AUTHORS ChangeLog COPYING

@UI_AUTO_AM@

all-local: ui-auto-all
clean-local: ui-auto-clean
distclean-local: ui-auto-distclean
install-data-local: ui-auto-install-data
install-exec-local: ui-auto-install-exec
uninstall-local: ui-auto-uninstall
dist-hook: ui-auto-dist
