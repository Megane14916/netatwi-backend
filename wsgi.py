"""WSGI entry; application creation is explicit at server startup."""

from app import create_app

app = create_app()
