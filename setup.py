# coding=utf-8

from mini_buildd import version
from distutils.core import setup

setup(name = "mini-buildd",
      version = version.pkg_version,
      description = "Mini Debian build daemon",
      author = "Stephan Sürken",
      author_email = "absurd@debian.org",
      scripts = ["mini-buildd"],
      packages = ["mini_buildd", "mini_buildd.webapp"])
