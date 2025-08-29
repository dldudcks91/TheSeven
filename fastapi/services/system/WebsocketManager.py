from fastapi import FastAPI, WebSocket
import json
# websocket_manager.py
class WebsocketManager:
   

    def __init__(self):
        self.active_connections: dict[int, WebSocket] = {}

    async def connect(self, websocket: WebSocket, user_no: int):
        await websocket.accept()
        self.active_connections[user_no] = websocket

    def disconnect(self, user_no: int):
        self.active_connections.pop(user_no, None)

    async def send_personal_message(self, message: str, user_no: int):
        if self.active_connections.get(user_no):
            await self.active_connections[user_no].send_text(message)
    
    
    async def broadcast_message(self, message: dict):
        """모든 연결된 클라이언트에게 메시지 전송"""
        disconnected_users = []
        for user_no, connection in self.active_connections.items():
            try:
                await connection.send_text(json.dumps(message))
            except Exception as e:
                print(f"Failed to broadcast to user {user_no}: {e}")
                disconnected_users.append(user_no)
        # 실패한 연결들 정리
        for user_no in disconnected_users:
            self.disconnect(user_no)