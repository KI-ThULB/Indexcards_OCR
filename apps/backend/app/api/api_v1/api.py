from fastapi import APIRouter
from app.api.api_v1.endpoints import health, upload, batches, templates, ws
from app.api.api_v1.endpoints.reconcile import router as reconcile_router

api_router = APIRouter()
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(upload.router, prefix="/upload", tags=["upload"])
api_router.include_router(batches.router, prefix="/batches", tags=["batches"])
api_router.include_router(templates.router, prefix="/templates", tags=["templates"])
api_router.include_router(ws.router, prefix="/ws", tags=["ws"])
api_router.include_router(reconcile_router, prefix="/reconcile", tags=["reconcile"])
