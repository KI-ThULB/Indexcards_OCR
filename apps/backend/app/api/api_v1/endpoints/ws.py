import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.core.security import check_ws_auth
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
    await ws_manager.connect(websocket, batch_id)
    try:
        while True:
            # We don't expect messages from the client, just keep connection alive
            data = await websocket.receive_text()
            logger.debug(f"Received from client {batch_id}: {data}")
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, batch_id)
        logger.info(f"Client disconnected from batch {batch_id}")
    except Exception as e:
        logger.error(f"WebSocket error for batch {batch_id}: {e}")
        ws_manager.disconnect(websocket, batch_id)
