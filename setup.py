# -*- coding: utf-8 -*-
import os
import sys
import shutil
import distutils.core
import debian.changelog
import setuptools
import doc.apidoc

print "I: Using setuptools: {v}".format(v=setuptools.__version__)


def sphinx_build_workaround():
    build_dir = "build/sphinx"
    static_files_build_dir = build_dir + "/_static"
    template_files_build_dir = build_dir + "/_templates"
    template_files_source_dir = "doc/_templates"

    if not os.path.exists(static_files_build_dir):
        os.makedirs(static_files_build_dir)

    if not os.path.exists(template_files_build_dir):
        os.makedirs(template_files_build_dir)

    # copy template files
    file_list = os.listdir(template_files_source_dir)
    for f in file_list:
        shutil.copy(template_files_source_dir + "/" + f, template_files_build_dir)

    # copy main files
    shutil.copy("doc/conf.py", build_dir)
    shutil.copy("doc/index.rst", build_dir)

    # call local apidoc script (sphinx < 1.1)
    apidoc_arguments = ['doc/apidoc.py', '--force', '--output-dir', 'build/sphinx', 'mini_buildd']
    doc.apidoc.main(apidoc_arguments)

# This is a Debian native package, the version is in
# debian/changelog and nowhere else. We automagically get the
# version from there, and update the mini_buildd package's
# __init__.py
__version__ = str(debian.changelog.Changelog(file=open("./debian/changelog", "rb")).version)
with open("./mini_buildd/__init__.py", "wb") as version_py:
    version_py.write("""\
# -*- coding: utf-8 -*-
from __future__ import unicode_literals

__version__ = '{version}'
""".format(version=__version__))
print "I: Got version from changelog: {v}".format(v=__version__)

if "build_sphinx" in sys.argv:
    sphinx_build_workaround()

distutils.core.setup(
    name="mini-buildd",
    version=__version__,
    description="Mini Debian build daemon",
    author="Stephan Sürken",
    author_email="absurd@debian.org",
    scripts=["mini-buildd"],
    packages=["mini_buildd", "mini_buildd/models"],
    package_data={"mini_buildd": ["templates/mini_buildd/*.html",
                                  "templates/admin/*.html",
                                  "templates/admin/mini_buildd/*.html",
                                  "templatetags/*.py",
                                  "fixtures/*.json",
                                  "static/css/*.css",
                                  "static/images/*.png",
                                  "static/*.*"]})
