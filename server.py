# server.py
import os
from dotenv import load_dotenv

# Load environment variables before any application imports
load_dotenv()

from app import create_app

# Create the Flask app instance using the factory
app = create_app()

if __name__ == "__main__":
    """
    Runs the application using the standard Flask development server.
    This is ideal for development tasks that do not involve WebSockets.
    """
    # Use custom HOST/PORT/DEBUG env variables, which is more idiomatic for app.run
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 2000))

    # Enable debug mode based on the DEBUG environment variable
    # The reloader is also controlled by the debug flag.
    debug = os.getenv("DEBUG", "1") == "1"

    print(f"🚀 Starting standard Flask server at http://{host}:{port}")
    app.run(host=host, port=port, debug=debug)
