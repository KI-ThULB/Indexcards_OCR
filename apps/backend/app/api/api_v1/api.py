from fastapi import APIRouter, Depends
from app.api.api_v1.endpoints import config, health, upload, batches, templates, ws
from app.api.api_v1.endpoints.reconcile import router as reconcile_router
from app.core.security import require_auth

# The bearer-token guard (W-01) is applied to the HTTP routers. The WebSocket
# router is intentionally excluded here — it authenticates via Origin allow-list
# + ?token= query param inside the endpoint (a browser cannot set an
# Authorization header on a WebSocket handshake).
_http_auth = [Depends(require_auth)]

api_router = APIRouter()
api_router.include_router(config.router, prefix="/config", tags=["config"], dependencies=_http_auth)
api_router.include_router(health.router, prefix="/health", tags=["health"], dependencies=_http_auth)
api_router.include_router(upload.router, prefix="/upload", tags=["upload"], dependencies=_http_auth)
api_router.include_router(batches.router, prefix="/batches", tags=["batches"], dependencies=_http_auth)
api_router.include_router(templates.router, prefix="/templates", tags=["templates"], dependencies=_http_auth)
api_router.include_router(reconcile_router, prefix="/reconcile", tags=["reconcile"], dependencies=_http_auth)
api_router.include_router(ws.router, prefix="/ws", tags=["ws"])
