# Dummy config. Just put everything needed here to make django not freak out on doc building.

MIDDLEWARE_CLASSES = (
    "django.middleware.common.CommonMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware")

INSTALLED_APPS = (
    "django_extensions",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "mini_buildd")

SECRET_KEY = "doc has no key. doc needs no key."
