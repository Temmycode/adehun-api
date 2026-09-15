from typing import Dict, Set

from fastapi import WebSocket

from app.logging import get_logger

logger = get_logger(__name__)

# Per-user cap so one account cannot exhaust file descriptors by opening
# sockets in a loop. Oldest connection is closed when the cap is exceeded.
MAX_SOCKETS_PER_USER = 5


class WalletConnectionManager:
    """In-process registry of user -> open sockets. Not shared across workers."""

    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}

    async def connect(self, user_id: str, websocket: WebSocket):
        await websocket.accept()
        sockets = self.active_connections.setdefault(user_id, set())
        if len(sockets) >= MAX_SOCKETS_PER_USER:
            victim = next(iter(sockets))
            sockets.discard(victim)
            try:
                await victim.close(code=1000)
            except Exception:
                pass
        sockets.add(websocket)

    def disconnect(self, user_id: str, websocket: WebSocket):
        sockets = self.active_connections.get(user_id)
        if not sockets:
            return
        sockets.discard(websocket)
        if not sockets:
            self.active_connections.pop(user_id, None)

    async def send_to_user(self, user_id: str, message: dict):
        """Push a payload to every live socket for a user, pruning dead ones."""
        sockets = self.active_connections.get(user_id)
        if not sockets:
            return
        for connection in list(sockets):
            try:
                await connection.send_json(message)
            except Exception:
                logger.info("dropping dead websocket", extra={"user_id": user_id})
                self.disconnect(user_id, connection)


# Global singleton
ws_manager = WalletConnectionManager()
