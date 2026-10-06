"""The factory export is cold and accepts complete explicit configuration."""

from tests.integration.test_package_entry_contract import run_isolated


def test_importing_factory_does_not_create_a_default_application():
    run_isolated('''
        from flask import Flask
        def reject(*args, **kwargs):
            raise AssertionError("Import created an application")
        Flask.__init__ = reject
        from app import create_app
        assert callable(create_app)
    ''')


def test_complete_config_boots_without_required_environment_or_db_connection():
    run_isolated('''
        import os, socket
        import app.config as config
        from sqlalchemy.engine import Engine
        config.load_dotenv = lambda: None
        for key in ("SQLALCHEMY_DATABASE_URI", "SECRET_KEY", "FRONTEND_URL", "FLASK_DEBUG"):
            os.environ.pop(key, None)
        def reject(*args, **kwargs):
            raise AssertionError("Factory must not connect to a DB or external service")
        socket.socket.connect = reject
        socket.socket.connect_ex = reject
        Engine.connect = reject
        from app import create_app
        application = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "SECRET_KEY": "config-only", "FRONTEND_URL": "https://frontend.example"})
        assert application.config["SECRET_KEY"] == "config-only"
        assert len(application.view_functions) == 36
        assert application.test_client().get("/api/me").get_json() == {"logged_in": False}
    ''')
