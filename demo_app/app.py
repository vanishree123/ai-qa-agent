"""Demo login app: the safe target the QA agent tests against.

Run:  python -m demo_app.app
Valid credentials: demo / demo123
"""
import os

from flask import Flask, redirect, render_template_string, request, session, url_for

app = Flask(__name__)
app.secret_key = "demo-only-not-a-real-secret"

USERS = {"demo": "demo123"}

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{{ title }}</title></head>
<body>{{ body|safe }}</body></html>"""

LOGIN_BODY = """
<h1 data-testid="login-heading">Sign in</h1>
{% if error %}<div data-testid="error-message" role="alert">{{ error }}</div>{% endif %}
<form method="post" action="/login" novalidate>
  <label for="username">Username</label>
  <input id="username" name="username" type="text" data-testid="username-input" autocomplete="off">
  <label for="password">Password</label>
  <input id="password" name="password" type="password" data-testid="password-input" autocomplete="off">
  <button type="submit" data-testid="login-button">Log in</button>
</form>
"""

DASH_BODY = """
<h1 data-testid="welcome-message">Welcome, {{ user }}</h1>
<a href="/logout" data-testid="logout-link">Log out</a>
"""


def render(title, body_template, **ctx):
    body = render_template_string(body_template, **ctx)
    return render_template_string(PAGE, title=title, body=body)


@app.get("/")
def index():
    return redirect(url_for("dashboard" if "user" in session else "login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not username or not password:
            error = "Username and password are required"
        elif USERS.get(username) == password:
            session["user"] = username
            return redirect(url_for("dashboard"))
        else:
            error = "Invalid username or password"
    return render("Login", LOGIN_BODY, error=error)


@app.get("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))
    return render("Dashboard", DASH_BODY, user=session["user"])


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("DEMO_PORT", "5000")), debug=False)
