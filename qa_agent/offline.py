"""Deterministic stand-in for the model so the pipeline (safety, runner, report) can be verified without an API key."""

CASES = [
    {"id": "TC-001", "title": "valid login reaches dashboard", "type": "positive",
     "steps": ["Open /login", "Enter demo / demo123", "Click Log in"], "expected": "Dashboard shows 'Welcome, demo'"},
    {"id": "TC-002", "title": "wrong password shows error", "type": "negative",
     "steps": ["Open /login", "Enter demo / wrong", "Click Log in"], "expected": "Error 'Invalid username or password'"},
    {"id": "TC-003", "title": "empty fields show validation error", "type": "validation",
     "steps": ["Open /login", "Click Log in with empty fields"], "expected": "Error 'Username and password are required'"},
    {"id": "TC-004", "title": "sql injection text is rejected", "type": "security",
     "steps": ["Open /login", "Enter \"' OR '1'='1\" as username and password", "Click Log in"],
     "expected": "Login fails with the standard error"},
    {"id": "TC-005", "title": "logout returns to login", "type": "session",
     "steps": ["Log in", "Click Log out"], "expected": "Back on /login"},
    {"id": "TC-006", "title": "dashboard requires login", "type": "session",
     "steps": ["Open /dashboard without a session"], "expected": "Redirected to /login"},
]

SCRIPT = '''import re

from playwright.sync_api import Page, expect


def _login(page: Page, base_url: str, user: str, password: str):
    page.goto(f"{base_url}/login")
    page.get_by_test_id("username-input").fill(user)
    page.get_by_test_id("password-input").fill(password)
    page.get_by_test_id("login-button").click()


def test_valid_login_reaches_dashboard(page: Page, base_url: str):
    """TC-001"""
    _login(page, base_url, "demo", "demo123")
    expect(page).to_have_url(re.compile(r".*/dashboard"))
    expect(page.get_by_test_id("welcome-message")).to_have_text("Welcome, demo")


def test_wrong_password_shows_error(page: Page, base_url: str):
    """TC-002"""
    _login(page, base_url, "demo", "wrong")
    expect(page.get_by_test_id("error-message")).to_have_text("Invalid username or password")


def test_empty_fields_show_validation_error(page: Page, base_url: str):
    """TC-003"""
    page.goto(f"{base_url}/login")
    page.get_by_test_id("login-button").click()
    expect(page.get_by_test_id("error-message")).to_have_text("Username and password are required")


def test_sql_injection_text_is_rejected(page: Page, base_url: str):
    """TC-004"""
    _login(page, base_url, "' OR '1'='1", "' OR '1'='1")
    expect(page.get_by_test_id("error-message")).to_have_text("Invalid username or password")
    expect(page).to_have_url(re.compile(r".*/login"))


def test_logout_returns_to_login(page: Page, base_url: str):
    """TC-005"""
    _login(page, base_url, "demo", "demo123")
    page.get_by_test_id("logout-link").click()
    expect(page).to_have_url(re.compile(r".*/login"))


def test_dashboard_requires_login(page: Page, base_url: str):
    """TC-006"""
    page.goto(f"{base_url}/dashboard")
    expect(page).to_have_url(re.compile(r".*/login"))
'''
