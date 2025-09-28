# configs/database.py
"""
Flask database setup (SQLAlchemy + Alembic via Flask-Migrate).
- Create the extension objects here.
- Initialize (bind) them inside app/create_app().
- db_healthcheck() does a quick SELECT 1.
"""

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy import text

# Global extensions (created here; initialized/bound in app factory)
db = SQLAlchemy()
migrate = Migrate()

def db_healthcheck() -> bool:
    try:
        db.session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
