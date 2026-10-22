"""Model-driven test-case generation and Playwright/pytest script generation,
with a static-safety repair loop and a runtime repair loop (failing tests go back to the model)."""
import json

from .llm import MetaLlamaClient, extract_code, extract_json
from .safety import check_script

# Elements that only exist after login, so the anonymous page crawl cannot see them.
EXTRA_TEST_IDS = {"welcome-message", "logout-link", "error-message", "login-heading"}

ELEMENT_GUIDE = """Elements of the app (data-testid -> meaning):
- username-input, password-input: inputs on /login (use .fill)
- login-button: submit button on /login (use .click)
- login-heading: heading on /login with text "Sign in"
- error-message: shown on /login after a failed login or empty submit
- welcome-message: heading on /dashboard with text "Welcome, demo" (only after a successful login)
- logout-link: a LINK (not a button) on /dashboard; click it to log out"""

CASE_SYSTEM = (
    "You are a senior QA engineer. You design concise, executable UI test cases from a page "
    "description. Reply with JSON only."
)

CASE_PROMPT = """Page description (real elements scraped from the target):
{page}

Exact behaviour of the app under test (use these exact texts in "expected"; do not invent others):
- Valid credentials: username "demo", password "demo123".
- Successful login redirects to /dashboard, which shows exactly "Welcome, demo" and a "Log out" link.
- Wrong username or wrong password shows exactly "Invalid username or password" and stays on /login.
- Submitting with an empty username or empty password shows exactly "Username and password are required".
- Special characters or injection strings (e.g. "' OR '1'='1") as credentials are NOT valid; they show
  "Invalid username or password".
- Clicking "Log out" returns to /login, which shows the heading "Sign in".
- Opening /dashboard without being logged in redirects to /login (heading "Sign in").
- Do NOT add features that don't exist (no registration, password reset, lockout, remember-me).

Design {n} distinct test cases covering: positive login, wrong password, wrong username, empty fields,
injection-style input, logout, and unauthenticated access to /dashboard.

Return ONE JSON object of the form {{"test_cases": [ ... ]}}. Each item:
{{"id": "TC-001", "title": str, "type": "positive|negative|validation|security|session", "steps": [str], "expected": str}}.
Keep every string short and on one line, with no line breaks or unescaped double quotes inside strings.
No prose outside the JSON."""

CASE_REPAIR_PROMPT = """Your previous reply was not valid JSON (parser error: {error}).
Reply again with ONLY one valid JSON object {{"test_cases": [...]}}. Keep strings short, on one line,
with no unescaped double quotes inside strings.

Original request:
{request}"""

SCRIPT_SYSTEM = (
    "You write Python pytest tests using Playwright's sync API (pytest-playwright). "
    "Reply with exactly one Python code block and nothing else."
)

RULES = """Hard rules:
- Imports allowed ONLY: `import re`, `import pytest`, `from playwright.sync_api import Page, expect`.
- Every test function has exactly the parameters `page: Page, base_url: str`. These are provided by
  pytest-playwright. NEVER write `@pytest.fixture`, NEVER call `Page(...)` or `sync_playwright()`, and
  NEVER add other parameters.
- Navigate with `page.goto(f"{base_url}/login")`. Never hard-code any other URL.
- Use ONLY these data-testid values with `page.get_by_test_id(...)`: <<IDS>>. Never invent others.
- Assertions:
  * Text of an element: `expect(page.get_by_test_id("error-message")).to_have_text("Invalid username or password")`
  * URL: `expect(page).to_have_url(re.compile(r".*/dashboard"))`
  * `expect(page)` supports ONLY `to_have_url` and `to_have_title`. NEVER write `expect(page).to_have_text(...)`.
  * To check you are on the login page, assert the URL or `expect(page.get_by_test_id("login-heading")).to_have_text("Sign in")`.
- NEVER use `not_to_have_text` or `not_to_contain_text` (they fail when the element is missing). After a successful
  login there is no error-message element, so assert what should appear instead:
  `expect(page).to_have_url(re.compile(r".*/dashboard"))` and
  `expect(page.get_by_test_id("welcome-message")).to_have_text("Welcome, demo")`.
  To assert an element is absent use `expect(page.get_by_test_id("error-message")).to_have_count(0)`.
- To log in inside a test, repeat the fill/click steps inline (no fixtures).
- Name each function `test_<snake_case_of_title>` and add the case id in a one-line docstring.
- No file access, network calls, subprocess, eval/exec, JavaScript evaluation, or sleeps."""

EXAMPLE = '''Example of one correct test:
```python
def test_wrong_password(page: Page, base_url: str):
    """TC-002"""
    page.goto(f"{base_url}/login")
    page.get_by_test_id("username-input").fill("demo")
    page.get_by_test_id("password-input").fill("wrong")
    page.get_by_test_id("login-button").click()
    expect(page.get_by_test_id("error-message")).to_have_text("Invalid username or password")
```'''

SCRIPT_PROMPT = """Write ONE test file implementing these test cases, one test function per case.

Test cases:
{cases}

Page description:
{page}

{guide}

{rules}

{example}
"""

REPAIR_PROMPT = """Your previous script was rejected by the safety/syntax checker:
{problems}

Fix every problem and return the full corrected file as one Python code block.

Previous script:
```python
{script}
```"""

RUNTIME_REPAIR_PROMPT = """Your test file was run against the real app and some tests failed.

Failed tests:
{failures}

Error output (tail):
{output}

{guide}

{rules}

Fix the failing tests. Keep passing tests unchanged. Return the full corrected file as one Python code block.

Current script:
```python
{script}
```"""


def known_test_ids(page: dict) -> set[str]:
    scraped = {e["data-testid"] for e in page.get("elements", []) if e.get("data-testid")}
    return scraped | EXTRA_TEST_IDS


def _rules(ids: set[str]) -> str:
    return RULES.replace("<<IDS>>", ", ".join(f"`{i}`" for i in sorted(ids)))


def generate_cases(llm: MetaLlamaClient, page: dict, n: int = 8, max_attempts: int = 3) -> list[dict]:
    request = CASE_PROMPT.format(page=json.dumps(page, indent=2), n=n)
    prompt, temperature, cases = request, 0.2, None
    for attempt in range(1, max_attempts + 1):
        raw = llm.chat(CASE_SYSTEM, prompt, temperature=temperature, json_mode=True)
        try:
            cases = extract_json(raw)
            break
        except json.JSONDecodeError as e:
            print(f"Model returned invalid JSON (attempt {attempt}/{max_attempts}): {e}")
            if attempt == max_attempts:
                raise RuntimeError("Model failed to return valid JSON test cases; run again or use a larger model") from e
            prompt = CASE_REPAIR_PROMPT.format(error=e, request=request)
            temperature = 0.0
    if isinstance(cases, dict):
        cases = cases.get("test_cases") or cases.get("cases") or list(cases.values())[0]
    required = {"id", "title", "steps", "expected"}
    cases = [c for c in cases if isinstance(c, dict) and required <= c.keys()]
    if not cases:
        raise RuntimeError("Model returned no usable test cases")
    return cases


def _vet(llm: MetaLlamaClient, script: str, allowed_host: str, ids: set[str], max_repairs: int = 2) -> str:
    """Static-check a script; on violations, ask the model to fix them (up to max_repairs times)."""
    for attempt in range(max_repairs + 1):
        problems = check_script(script, allowed_host, ids)
        if not problems:
            return script
        if attempt == max_repairs:
            raise RuntimeError("Generated script failed safety checks:\n- " + "\n- ".join(problems))
        print(f"Script rejected by checker ({len(problems)} problem(s)); asking model to fix (attempt {attempt + 1})")
        raw = llm.chat(
            SCRIPT_SYSTEM,
            REPAIR_PROMPT.format(problems="\n".join(f"- {p}" for p in problems), script=script),
            temperature=0.0,
            max_tokens=6000,
        )
        script = extract_code(raw)
    return script


def generate_script(llm: MetaLlamaClient, page: dict, cases: list[dict], allowed_host: str, max_repairs: int = 2) -> str:
    ids = known_test_ids(page)
    raw = llm.chat(
        SCRIPT_SYSTEM,
        SCRIPT_PROMPT.format(
            cases=json.dumps(cases, indent=2), page=json.dumps(page, indent=2),
            guide=ELEMENT_GUIDE, rules=_rules(ids), example=EXAMPLE,
        ),
        temperature=0.1,
        max_tokens=6000,
    )
    return _vet(llm, extract_code(raw), allowed_host, ids, max_repairs)


def repair_script(llm: MetaLlamaClient, page: dict, script: str, result: dict, allowed_host: str) -> str:
    """Send failing tests and their errors back to the model and return a corrected, vetted script."""
    ids = known_test_ids(page)
    failed = [t for t in result["tests"] if t["status"] != "passed"]
    failures = "\n".join(f"- {t['name']}: {t['detail'] or 'failed'}" for t in failed)
    raw = llm.chat(
        SCRIPT_SYSTEM,
        RUNTIME_REPAIR_PROMPT.format(
            failures=failures, output=result.get("stdout", "")[-3500:],
            guide=ELEMENT_GUIDE, rules=_rules(ids), script=script,
        ),
        temperature=0.0,
        max_tokens=6000,
    )
    return _vet(llm, extract_code(raw), allowed_host, ids)
