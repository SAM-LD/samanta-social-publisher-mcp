from api import _bootstrap

_bootstrap()

from api.index import app
from api.privacy import router as privacy_router

app.include_router(privacy_router)

__all__ = ["app"]
