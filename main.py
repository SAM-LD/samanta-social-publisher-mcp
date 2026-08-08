from api import _bootstrap

_bootstrap()

from api.meta_error_bridge import install_meta_error_bridge
install_meta_error_bridge()

from api.index import app
from api.privacy import router as privacy_router
from api.meta_manual import router as meta_manual_router

app.include_router(privacy_router)
app.include_router(meta_manual_router)

__all__ = ["app"]
