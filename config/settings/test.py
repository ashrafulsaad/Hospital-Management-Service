from .base import *

# Fast hasher: ONLY for tests. Never use MD5 for real passwords.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
