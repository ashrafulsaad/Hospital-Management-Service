from .base import *

DEBUG = True
ALLOWED_HOSTS = [
    *ALLOWED_HOSTS,
    "0.0.0.0",
    "[::1]",
]
