import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.core.security import check_ws_auth
from app.core.error_reporting import report_error
from app.services.ws_manager import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter()

@router.websocket("/task/{batch_id}")
async def websocket_endpoint(websocket: WebSocket, batch_id: str):
    # Reject cross-site origins and (when configured) a missing/invalid token
    # BEFORE accepting the handshake (W-04/H-4).
    if not check_ws_auth(websocket):
        await websocket.close(code=1008)
        logger.warning(f"Rejected WebSocket handshake for batch {batch_id} (origin/token check failed)")
        return
    try:
        await ws_manager.connect(websocket, batch_id)
        while True:
            # We don't expect messages from the client, just keep connection alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, batch_id)
        logger.info(f"Client disconnected from batch {batch_id}")
    except Exception as e:
        identifier = report_error(logger, "ws_delivery_failed", "websocket.session", e, scope=websocket.scope)
        ws_manager.disconnect(websocket, batch_id)
        try:
            await websocket.close(code=1011, reason=f"WebSocket processing failed. Reference: {identifier}")
        except Exception as close_exc:
            report_error(logger, "ws_close_failed", "websocket.close", close_exc, scope=websocket.scope)
