# -*- coding: utf-8 -*-
import os
import sys
import shutil
import subprocess
import distutils.core
import debian.changelog
import setuptools
import doc.apidoc

print "I: Using setuptools: {v}".format(v=setuptools.__version__)


def sphinx_build_workaround(build_dir="./build/sphinx"):
    # Prepare build dir: doc/, plus static files from app.mini_buildd
    shutil.rmtree(build_dir, ignore_errors=True)
    shutil.copytree("./doc", build_dir)
    shutil.copytree("./mini_buildd/static", os.path.join(build_dir, "_static"))

    # Call apidoc (local script for sphinx < 1.1)
    apidoc = "/usr/bin/sphinx-apidoc" if os.path.exists("/usr/bin/sphinx-apidoc") else "./doc/apidoc.py"
    apidoc_arguments = [apidoc, "--force", "--output-dir", build_dir, "./mini_buildd/"]
    doc.apidoc.main(apidoc_arguments)

    # Generate man pages via help2man
    subprocess.check_call(["help2man",
                           "--no-info", "--no-discard-stderr",
                           "--output=" + build_dir + "/mini-buildd.8", "--section=8",
                           "--include=doc/mini-buildd.help2man.include", "./mini-buildd"])
    subprocess.check_call(["help2man",
                           "--no-info", "--no-discard-stderr",
                           "--output=" + build_dir + "/mini-buildd-tool.1", "--section=1",
                           r"--name=mini-buildd-tool \- User/client tool box for mini-buildd instances.", "./mini-buildd-tool"])

# This is a Debian native package, the version is in
# debian/changelog and nowhere else. We automagically get the
# version from there, and update the mini_buildd package's
# __init__.py
__version__ = str(debian.changelog.Changelog(file=open("./debian/changelog", "rb")).version)
with open("./mini_buildd/__init__.py", "wb") as version_py:
    version_py.write("""\
# -*- coding: utf-8 -*-
from __future__ import unicode_literals

__version__ = "{version}"
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
    scripts=["mini-buildd", "mini-buildd-tool"],
    packages=["mini_buildd", "mini_buildd/models"],
    package_data={"mini_buildd": ["templates/*.html",
                                  "templates/mini_buildd/*.html",
                                  "templates/admin/*.html",
                                  "templates/admin/mini_buildd/*.html",
                                  "templates/registration/*.html",
                                  "templates/registration/*.txt",
                                  "templatetags/*.py",
                                  "static/css/*.css",
                                  "static/js/*.js",
                                  "static/img/*.png",
                                  "static/img/*.gif",
                                  "static/*.*"]})
