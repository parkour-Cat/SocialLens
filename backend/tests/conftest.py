from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sociallens.config import Settings
from sociallens.main import create_app


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path / "data", log_level="DEBUG", ws_heartbeat_s=5.0, download_proxy="off")


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def token(app) -> str:
    return app.state.sl.token
