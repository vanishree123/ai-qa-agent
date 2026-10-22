from qa_agent.offline import SCRIPT
from qa_agent.safety import check_script

HOST = "127.0.0.1"


def test_offline_script_is_clean():
    assert check_script(SCRIPT, HOST) == []


def test_rejects_forbidden_import():
    src = "import os\ndef test_x():\n    pass\n"
    assert any("import 'os'" in p for p in check_script(src, HOST))


def test_rejects_foreign_url():
    src = 'def test_x():\n    u = "https://evil.example.com/x"\n'
    assert any("evil.example.com" in p for p in check_script(src, HOST))


def test_rejects_eval_and_open():
    src = "def test_x():\n    eval('1')\n    open('f')\n"
    problems = check_script(src, HOST)
    assert any("eval" in p for p in problems) and any("open" in p for p in problems)


def test_rejects_js_evaluate():
    src = "def test_x(page):\n    page.evaluate('1')\n"
    assert any("evaluate" in p for p in check_script(src, HOST))


def test_rejects_custom_page_fixture_and_page_constructor():
    src = (
        "import pytest\n"
        "from playwright.sync_api import Page\n"
        "@pytest.fixture\n"
        "def page():\n"
        "    return Page()\n"
        "def test_x(page: Page):\n"
        "    pass\n"
    )
    problems = check_script(src, HOST)
    assert any("do not define fixtures" in p for p in problems)
    assert any("never create 'Page'" in p for p in problems)


def test_rejects_expect_page_to_have_text():
    src = (
        "from playwright.sync_api import Page, expect\n"
        "def test_x(page: Page, base_url: str):\n"
        "    expect(page).to_have_text('Sign in')\n"
    )
    assert any("expect(page) only supports" in p for p in check_script(src, HOST))


def test_allows_page_url_assertion_and_element_text():
    src = (
        "import re\n"
        "from playwright.sync_api import Page, expect\n"
        "def test_x(page: Page, base_url: str):\n"
        "    expect(page).to_have_url(re.compile(r'.*/login'))\n"
        "    expect(page.get_by_test_id('error-message')).to_have_text('x')\n"
    )
    assert check_script(src, HOST) == []


def test_rejects_unknown_test_id_when_ids_given():
    src = (
        "from playwright.sync_api import Page\n"
        "def test_x(page: Page, base_url: str):\n"
        "    page.get_by_test_id('logout-button').click()\n"
    )
    ids = {"logout-link", "login-button"}
    assert any("unknown test id 'logout-button'" in p for p in check_script(src, HOST, ids))
    assert check_script(src, HOST) == []  # no id list -> not enforced


def test_offline_script_passes_with_known_ids():
    ids = {"username-input", "password-input", "login-button", "error-message",
           "welcome-message", "logout-link", "login-heading"}
    assert check_script(SCRIPT, HOST, ids) == []


def test_rejects_negated_text_assertion_and_allows_count_zero():
    bad = (
        "from playwright.sync_api import Page, expect\n"
        "def test_x(page: Page, base_url: str):\n"
        "    expect(page.get_by_test_id('error-message')).not_to_have_text('Invalid username or password')\n"
    )
    assert any("not_to_have_text" in p for p in check_script(bad, HOST))
    good = bad.replace("not_to_have_text('Invalid username or password')", "to_have_count(0)")
    assert check_script(good, HOST) == []


def test_rejects_unknown_test_fixtures():
    problems = check_script("def test_x(page, browser_name):\n    pass\n", HOST)
    assert any("unknown fixtures" in p for p in problems)


def test_rejects_syntax_error_and_missing_tests():
    assert check_script("def test_x(:\n", HOST)[0].startswith("SyntaxError")
    assert "no test_* functions found" in check_script("x = 1\n", HOST)
