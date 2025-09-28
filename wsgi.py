# # wsgi.py

from app import create_app

app = create_app()
application = app  # some process managers expect this name
