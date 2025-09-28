# socket_server.py
import os
from dotenv import load_dotenv

load_dotenv()  # load .env BEFORE imports that read env

from app import create_app
from app.websockets.socketio_app import init_socketio

app = create_app()
socketio = init_socketio(app)

if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 7000))
    debug = os.getenv("DEBUG", "1") == "1"

    print(f"🚀 Socket.IO dev server: http://{host}:{port}")
    socketio.run(app, host=host, port=port, debug=debug)
