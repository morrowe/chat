import os
import json
import asyncio
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import redis.asyncio as aioredis
import asyncpg

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:secret_pass@localhost:5432/chat_db")

redis_client = aioredis.from_url(f"redis://{REDIS_HOST}:{REDIS_PORT}")
db_pool = None

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast_raw(self, message_text: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message_text)
            except Exception:
                pass

manager = ConnectionManager()

async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL)
    async with db_pool.acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id VARCHAR(255) PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(255) REFERENCES users(id) ON DELETE CASCADE,
                text TEXT NOT NULL,
                reply_to INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        ''')

async def redis_listener():
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("redis_chat_channel")
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                await manager.broadcast_raw(message["data"].decode("utf-8"))
    except asyncio.CancelledError:
        await pubsub.unsubscribe("redis_chat_channel")

@app.on_event("startup")
async def startup_event():
    await init_db()
    asyncio.create_task(redis_listener())

@app.on_event("shutdown")
async def shutdown_event():
    if db_pool:
        await db_pool.close()

@app.get("/")
async def get():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    
    async with db_pool.acquire() as conn:
        rows = await conn.fetch('''
            SELECT id, user_id, text, reply_to, created_at 
            FROM messages 
            ORDER BY id ASC LIMIT 50;
        ''')
        for row in rows:
            history_msg = {
                "type": "message",
                "id": row["id"],
                "username": row["user_id"],
                "text": row["text"],
                "reply_to": row["reply_to"],
                "time": row["created_at"].isoformat()
            }
            await websocket.send_text(json.dumps(history_msg))

    try:
        while True:
            raw_data = await websocket.receive_text()
            data = json.loads(raw_data)
            
            username = data.get("username", "Гость").strip()
            text = data.get("text", "").strip()
            reply_to = data.get("reply_to")

            if not text:
                continue

            async with db_pool.acquire() as conn:
                await conn.execute('''
                    INSERT INTO users (id) VALUES ($1)
                    ON CONFLICT (id) DO NOTHING;
                ''', username)

                row = await conn.fetchrow('''
                    INSERT INTO messages (user_id, text, reply_to) 
                    VALUES ($1, $2, $3) 
                    RETURNING id, created_at;
                ''', username, text, reply_to)

            payload = {
                "type": "message",
                "id": row["id"],
                "username": username,
                "text": text,
                "reply_to": reply_to,
                "time": row["created_at"].isoformat()
            }

            await redis_client.publish("redis_chat_channel", json.dumps(payload))

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        manager.disconnect(websocket)
