import pytest

from demo_app.app import app


@pytest.fixture
def client():
    return app.test_client()


def test_login_page_renders(client):
    assert b'data-testid="login-button"' in client.get("/login").data


def test_valid_login_redirects_to_dashboard(client):
    r = client.post("/login", data={"username": "demo", "password": "demo123"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/dashboard")


def test_invalid_login_shows_error(client):
    r = client.post("/login", data={"username": "demo", "password": "nope"})
    assert b"Invalid username or password" in r.data


def test_empty_fields_validation(client):
    r = client.post("/login", data={"username": "", "password": ""})
    assert b"Username and password are required" in r.data


def test_dashboard_requires_session(client):
    r = client.get("/dashboard")
    assert r.status_code == 302 and r.headers["Location"].endswith("/login")
