"""ASGI object for uvicorn: `uvicorn sociallens.asgi:app`. Kept separate so importing
sociallens.main has no side effects (tests build their own app with temp settings)."""

from .main import create_app

app = create_app()
