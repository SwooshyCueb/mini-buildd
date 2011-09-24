# -*- coding: utf-8 -*-
from distutils.core import setup
from debian.changelog import Changelog, Version

# This is a Debian native package, the version is in
# debian/changelog and nowhere else. We automagically get the
# version from there, and update the mini_buildd package's
# __version__.py
__version__ = str(Changelog(file=open("./debian/changelog", "rb")).version)
with open("./mini_buildd/__version__.py", "wb") as version_py:
    version_py.write("# -*- coding: utf-8 -*-\n__version__ = '{version}'".format(version=__version__))
print "I: Got version from changelog: {v}".format(v=__version__)

setup(name = "mini-buildd",
      version = __version__,
      description = "Mini Debian build daemon",
      author = "Stephan Sürken",
      author_email = "absurd@debian.org",
      scripts = ["mini-buildd"],
      packages = ["mini_buildd"],
      package_data = {"mini_buildd": ["templates/mini_buildd/*.html", "fixtures/*.json"]})
