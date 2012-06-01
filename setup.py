# -*- coding: utf-8 -*-
import os
import sys
import shutil
import distutils.core
import debian.changelog
from setuptools import setup
from doc import apidoc

def sphinx_build_workaround():
    sphinx_build_dir = "build/sphinx"
    sphinx_static_files_build_dir = sphinx_build_dir + "/_static"
    sphinx_static_files_source_dir = "doc/_static"

    if not os.path.exists(sphinx_static_files_build_dir):
        os.makedirs(sphinx_static_files_build_dir)

    # copy static files (shutil.copytree does not fit our needs)
    file_list = os.listdir(sphinx_static_files_source_dir)
    for f in file_list:
        shutil.copy(sphinx_static_files_source_dir + "/" + f, sphinx_static_files_build_dir)

    # copy main files
    shutil.copy("doc/conf.py", sphinx_build_dir)
    shutil.copy("doc/index.rst", sphinx_build_dir)

    # call local apidoc script (sphinx < 1.1)
    apidoc_arguments = ['doc/apidoc.py', '--force', '--output-dir', 'build/sphinx', 'mini_buildd']
    apidoc.main(apidoc_arguments)

# This is a Debian native package, the version is in
# debian/changelog and nowhere else. We automagically get the
# version from there, and update the mini_buildd package's
# __version__.py
__version__ = str(debian.changelog.Changelog(file=open("./debian/changelog", "rb")).version)
with open("./mini_buildd/__init__.py", "wb") as version_py:
    version_py.write("""\
# -*- coding: utf-8 -*-
__version__ = '{version}'
""".format(version=__version__))
print "I: Got version from changelog: {v}".format(v=__version__)

if "build_sphinx" in sys.argv:
    sphinx_build_workaround()

distutils.core.setup(
    name = "mini-buildd",
    version = __version__,
    description = "Mini Debian build daemon",
    author = "Stephan Sürken",
    author_email = "absurd@debian.org",
    scripts = ["mini-buildd"],
    packages = ["mini_buildd"],
    package_data = {"mini_buildd": ["templates/mini_buildd/*.html", "templatetags/*.py", "fixtures/*.json"]})
