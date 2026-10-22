"""Static safety checks for model-generated test scripts. Nothing runs unless this returns no violations."""
import ast
import re
from urllib.parse import urlparse

ALLOWED_IMPORTS = {"pytest", "re", "playwright.sync_api"}
FORBIDDEN_CALLS = {"eval", "exec", "compile", "open", "__import__", "input", "breakpoint", "globals", "locals", "vars"}
FORBIDDEN_ATTRS = {
    "evaluate", "evaluate_handle", "add_init_script", "expose_function", "expose_binding",
    "route", "new_context", "launch", "connect", "connect_over_cdp",
}
FORBIDDEN_CONSTRUCTORS = {"Page", "Browser", "BrowserContext", "Playwright", "sync_playwright"}
ALLOWED_TEST_ARGS = {"page", "base_url"}
URL_RE = re.compile(r"https?://[^\s'\"]+", re.IGNORECASE)


PAGE_ASSERTIONS = {"to_have_url", "to_have_title"}
NEGATED_TEXT_ASSERTIONS = {"not_to_have_text", "not_to_contain_text"}


def check_script(source: str, allowed_host: str, known_test_ids: set[str] | None = None) -> list[str]:
    """Return a list of human-readable violations (empty list means the script is acceptable).

    known_test_ids: if given, every page.get_by_test_id("...") must use one of these ids.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [f"SyntaxError at line {e.lineno}: {e.msg}"]

    problems: list[str] = []
    has_test = False

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in ALLOWED_IMPORTS:
                    problems.append(f"line {node.lineno}: import '{alias.name}' is not allowed")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "") not in ALLOWED_IMPORTS or node.level:
                problems.append(f"line {node.lineno}: import from '{node.module}' is not allowed")
        elif isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id in FORBIDDEN_CALLS:
                problems.append(f"line {node.lineno}: call to '{fn.id}()' is not allowed")
            if isinstance(fn, ast.Name) and fn.id in FORBIDDEN_CONSTRUCTORS:
                problems.append(
                    f"line {node.lineno}: never create '{fn.id}' yourself; use the 'page' fixture passed to the test"
                )
            if isinstance(fn, ast.Attribute) and fn.attr in FORBIDDEN_ATTRS:
                problems.append(f"line {node.lineno}: use of '.{fn.attr}()' is not allowed")
            if isinstance(fn, ast.Attribute) and fn.attr in NEGATED_TEXT_ASSERTIONS:
                problems.append(
                    f"line {node.lineno}: '.{fn.attr}()' fails when the element does not exist; to check something is "
                    "absent use expect(locator).to_have_count(0) or .not_to_be_visible(), and prefer asserting what "
                    "SHOULD appear (e.g. welcome-message text or the /dashboard URL)"
                )
            if isinstance(fn, ast.Attribute):
                base = fn.value
                if (
                    isinstance(base, ast.Call) and isinstance(base.func, ast.Name) and base.func.id == "expect"
                    and base.args and isinstance(base.args[0], ast.Name) and base.args[0].id == "page"
                    and fn.attr not in PAGE_ASSERTIONS
                ):
                    problems.append(
                        f"line {node.lineno}: expect(page) only supports to_have_url/to_have_title; "
                        f"for '{fn.attr}' use an element, e.g. expect(page.get_by_test_id('error-message')).{fn.attr}(...)"
                    )
                if (
                    fn.attr == "get_by_test_id" and known_test_ids is not None and node.args
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
                    and node.args[0].value not in known_test_ids
                ):
                    problems.append(
                        f"line {node.lineno}: unknown test id '{node.args[0].value}'; "
                        f"use only one of {sorted(known_test_ids)}"
                    )
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__") and node.attr.endswith("__"):
                problems.append(f"line {node.lineno}: dunder attribute '{node.attr}' is not allowed")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            for url in URL_RE.findall(node.value):
                host = urlparse(url).hostname
                if host != allowed_host:
                    problems.append(f"line {node.lineno}: URL host '{host}' is not the allowed target '{allowed_host}'")
        elif isinstance(node, ast.FunctionDef):
            for dec in node.decorator_list:
                target = dec.func if isinstance(dec, ast.Call) else dec
                name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
                if name == "fixture":
                    problems.append(
                        f"line {node.lineno}: do not define fixtures; use the built-in 'page' and 'base_url' fixtures"
                    )
            if node.name.startswith("test_"):
                has_test = True
                extra = [a.arg for a in node.args.args if a.arg not in ALLOWED_TEST_ARGS]
                if extra:
                    problems.append(
                        f"line {node.lineno}: test '{node.name}' uses unknown fixtures {extra}; "
                        "only 'page' and 'base_url' are allowed"
                    )

    if not has_test:
        problems.append("no test_* functions found")
    return problems
