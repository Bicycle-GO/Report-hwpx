import pytest
from fastapi.testclient import TestClient
from app import storage
from app.main import app

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(storage,"DATA",tmp_path)
    with TestClient(app,headers={"X-Report-Client":"studio-v1"}) as c:
        yield c

