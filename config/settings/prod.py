import os

from .base import *  # noqa: F403

DEBUG = False
# KeyError on purpose: prod must not start with missing secrets.
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
ALLOWED_HOSTS = [h for h in os.environ["DJANGO_ALLOWED_HOSTS"].split(",") if h]
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
# More hardening (HTTPS redirect, HSTS, headers) comes in Chunk 13.
