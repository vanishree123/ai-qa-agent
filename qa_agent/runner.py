"""Sandbox-ish executor: runs a vetted test file with pytest in an isolated output dir, with secrets stripped from env."""
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

SECRET_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "LLAMA", "GITHUB")


def _clean_env() -> dict:
    return {k: v for k, v in os.environ.items() if not any(m in k.upper() for m in SECRET_MARKERS)}


def start_demo_app(port: int, project_root: Path) -> subprocess.Popen:
    env = _clean_env()
    env["DEMO_PORT"] = str(port)
    proc = subprocess.Popen(
        [sys.executable, "-m", "demo_app.app"], cwd=project_root, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            if requests.get(f"http://127.0.0.1:{port}/health", timeout=1).ok:
                return proc
        except requests.RequestException:
            time.sleep(0.3)
    proc.terminate()
    raise RuntimeError("Demo app did not start within 15s")


def run_tests(test_file: Path, base_url: str, run_dir: Path, timeout: int = 180, headed: bool = False) -> dict:
    junit = run_dir / "junit.xml"
    cmd = [
        sys.executable, "-m", "pytest", str(test_file.name),
        "--base-url", base_url,
        "--junitxml", str(junit),
        "--output", str(run_dir / "artifacts"),
        "--screenshot", "only-on-failure",
        "-p", "no:cacheprovider", "-q",
    ]
    if headed:
        cmd.append("--headed")
    try:
        proc = subprocess.run(
            cmd, cwd=run_dir, env=_clean_env(), capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return {"exit_code": -1, "timed_out": True, "tests": [], "stdout": "", "stderr": f"Timed out after {timeout}s"}

    tests = []
    if junit.exists():
        for case in ET.parse(junit).getroot().iter("testcase"):
            status, detail = "passed", ""
            for tag in ("failure", "error", "skipped"):
                el = case.find(tag)
                if el is not None:
                    status = "failed" if tag in ("failure", "error") else "skipped"
                    detail = (el.get("message") or "")[:400]
            tests.append({"name": case.get("name"), "status": status, "detail": detail})
    return {
        "exit_code": proc.returncode, "timed_out": False, "tests": tests,
        "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-2000:],
    }
