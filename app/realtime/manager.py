from app.logging import get_logger
from fastapi import WebSocket
from typing import Set, Dict


class WalletConnectionManager:
    def __init__(self):
        # Maps user_id -> Set of WebSockets (to support multiple devices logged into one account)
        self.active_connections: Dict[str, Set[WebSocket]] = {}

    async def connect(self, user_id: str, websocket: WebSocket):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = set()
        self.active_connections[user_id].add(websocket)

    def disconnect(self, user_id: str, websocket: WebSocket):
        if user_id in self.active_connections:
            self.active_connections[user_id].remove(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]

    async def send_to_user(self, user_id: str, message: dict):
        """Pushes a payload to all active sockets for a specific user."""
        if user_id in self.active_connections:
            for connection in self.active_connections[user_id]:
                await connection.send_json(message)


# Global singleton
ws_manager = WalletConnectionManager()
