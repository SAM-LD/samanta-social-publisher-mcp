from api import _bootstrap

_bootstrap()

from api.index import app
from api.privacy import router as privacy_router
from api.meta_manual import router as meta_manual_router

app.include_router(privacy_router)
app.include_router(meta_manual_router)

__all__ = ["app"]
