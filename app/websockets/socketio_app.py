# app/websockets/socketio_app.py
from flask_socketio import SocketIO, emit, join_room, leave_room
import time
from config.settings import settings  # uses your existing settings (CORS + REDIS_URL)

# Create a SocketIO instance (not yet bound to the Flask app)
# - async_mode=None lets Flask-SocketIO auto-detect (eventlet/gevent/threading)
# - message_queue uses Redis to allow cross-process emits (optional but good)
socketio = SocketIO(
    async_mode=None,
    cors_allowed_origins=settings.CORS_ALLOWED_ORIGINS,
    message_queue=settings.REDIS_URL,
    manage_session=False,  # you're using server-side sessions (Flask-Session)
)

def init_socketio(app):
    """
    Bind Socket.IO to the Flask app and register event handlers.
    Call this once at startup.
    """
    socketio.init_app(
        app,
        cors_allowed_origins=settings.CORS_ALLOWED_ORIGINS,
    )
    register_handlers()
    return socketio

def register_handlers():
    @socketio.on("connect")
    def on_connect():
        emit("connected", {"ok": True, "ts": time.time()})

    @socketio.on("disconnect")
    def on_disconnect():
        # optional logging
        pass

    @socketio.on("ping")
    def on_ping(data=None):
        emit("pong", data or {"ts": time.time()})

    @socketio.on("join")
    def on_join(data):
        room = (data or {}).get("room")
        if room:
            join_room(room)
            emit("joined", {"room": room})

    @socketio.on("leave")
    def on_leave(data):
        room = (data or {}).get("room")
        if room:
            leave_room(room)
            emit("left", {"room": room})

# Example helper to broadcast stock changes (use anywhere in your code)
def push_stock_update(item_id: int, qty: float, room: str | None = None):
    payload = {"item_id": item_id, "qty": qty, "ts": time.time()}
    if room:
        socketio.emit("stock_update", payload, to=room)
    else:
        socketio.emit("stock_update", payload, broadcast=True)
