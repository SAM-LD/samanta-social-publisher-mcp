from api import _bootstrap

_bootstrap()

from api.index import app

__all__ = ["app"]
