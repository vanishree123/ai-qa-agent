"""Pipeline: inspect target -> generate cases -> generate script -> safety check -> run -> report."""
import argparse
import json
import socket
from datetime import datetime
from pathlib import Path

from . import offline
from .config import load_settings
from .generator import generate_cases, generate_script, repair_script
from .inspector import inspect_page
from .llm import MetaLlamaClient
from .runner import run_tests, start_demo_app
from .safety import check_script

ROOT = Path(__file__).resolve().parent.parent


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _score(result: dict) -> tuple[int, int]:
    return sum(t["status"] == "passed" for t in result["tests"]), len(result["tests"])


def write_report(run_dir: Path, cases: list[dict], result: dict, mode: str, target: str,
                 history: list[tuple[int, int]] | None = None) -> Path:
    passed = sum(t["status"] == "passed" for t in result["tests"])
    lines = [
        "# AI QA Agent report", "",
        f"- Mode: {mode}", f"- Target: {target}", f"- Result: {passed}/{len(result['tests'])} passed",
    ]
    if history and len(history) > 1:
        lines.append("- Pass rate per attempt: " + " -> ".join(f"{p}/{t}" for p, t in history))
    lines += ["", "## Test cases", ""]
    lines += [f"- **{c['id']}** {c['title']} ({c.get('type', '-')}): {c['expected']}" for c in cases]
    lines += ["", "## Results", ""]
    lines += [f"- {t['status'].upper()}: {t['name']} {t['detail']}".rstrip() for t in result["tests"]]
    if result["exit_code"] not in (0, 1) or result.get("timed_out"):
        lines += ["", "## Runner output", "", "```", result["stdout"] + result["stderr"], "```"]
    path = run_dir / "report.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def cmd_check_api(args) -> int:
    settings = load_settings()
    llm = MetaLlamaClient(settings)
    print(f"Endpoint: {settings.base_url}\nModel: {settings.model}")
    try:
        print("Available models:", ", ".join(llm.list_models()) or "(none returned)")
    except Exception as e:  # models listing may be unsupported; chat is the real test
        print(f"(model listing unavailable: {e})")
    print("Reply:", llm.chat("You are terse.", "Reply with the single word: ready", max_tokens=10))
    return 0


def cmd_run(args) -> int:
    settings = load_settings(args.target)
    demo = None
    target = settings.target_url
    if args.start_demo:
        port = _free_port()
        demo = start_demo_app(port, ROOT)
        target = f"http://127.0.0.1:{port}"
        settings = load_settings(target)
        print(f"Demo app started at {target}")
    try:
        page = inspect_page(f"{target}/login")
        print(f"Inspected {target}/login: {len(page['elements'])} elements")

        llm = None
        if args.offline:
            mode, cases, script = "offline (no model)", offline.CASES, offline.SCRIPT
        else:
            llm = MetaLlamaClient(settings)
            mode = f"Meta {settings.model}"
            cases = generate_cases(llm, page, n=args.cases)
            print(f"Model produced {len(cases)} test cases")
            script = generate_script(llm, page, cases, settings.target_host)
        problems = check_script(script, settings.target_host)
        if problems:
            raise SystemExit("Safety check failed:\n- " + "\n- ".join(problems))
        print("Safety check passed")

        run_dir = ROOT / "out" / datetime.now().strftime("%Y%m%d-%H%M%S")
        run_dir.mkdir(parents=True)
        (run_dir / "cases.json").write_text(json.dumps(cases, indent=2), encoding="utf-8")
        test_file = run_dir / "test_generated.py"
        test_file.write_text(script, encoding="utf-8")

        result = run_tests(test_file, target, run_dir, timeout=args.timeout, headed=args.headed)
        history = [_score(result)]
        print(f"First run: {history[0][0]}/{history[0][1]} passed")

        # Runtime repair loop: send failing tests + errors back to the model, keep the better script.
        for rnd in range(1, args.repair_rounds + 1):
            failed = [t for t in result["tests"] if t["status"] != "passed"]
            if llm is None or not failed:
                break
            print(f"Repair round {rnd}: asking the model to fix {len(failed)} failing test(s)...")
            try:
                new_script = repair_script(llm, page, script, result, settings.target_host)
            except Exception as e:  # model unreachable/timeout/bad output: keep the results we already have
                print(f"Repair skipped ({type(e).__name__}: {str(e)[:200]}). Keeping the first run's results.")
                print("Tip: check Ollama is running (http://localhost:11434) and re-run, or use --repair-rounds 0")
                break
            (run_dir / f"test_generated.attempt{rnd - 1}.py").write_text(script, encoding="utf-8")
            test_file.write_text(new_script, encoding="utf-8")
            new_result = run_tests(test_file, target, run_dir, timeout=args.timeout, headed=args.headed)
            history.append(_score(new_result))
            print(f"After repair {rnd}: {history[-1][0]}/{history[-1][1]} passed")
            if history[-1][0] >= history[-2][0]:
                script, result = new_script, new_result
            else:
                test_file.write_text(script, encoding="utf-8")  # repair made things worse; keep previous
                print("Repair did not improve the result; keeping the previous script")
                break

        (run_dir / "results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        report = write_report(run_dir, cases, result, mode, target, history)
        passed, total = _score(result)
        print(f"Tests: {passed}/{total} passed\nReport: {report}")
        return 0 if result["exit_code"] == 0 else 1
    finally:
        if demo:
            demo.terminate()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="qa_agent", description="AI QA agent MVP")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("check-api", help="Verify Meta Llama API access").set_defaults(func=cmd_check_api)
    r = sub.add_parser("run", help="Generate and execute tests")
    r.add_argument("--target", help="Override TARGET_URL (must be local)")
    r.add_argument("--start-demo", action="store_true", help="Start the bundled demo app on a free port")
    r.add_argument("--offline", action="store_true", help="Skip the model; use built-in cases and script")
    r.add_argument("--cases", type=int, default=8, help="Number of test cases to request")
    r.add_argument("--repair-rounds", type=int, default=1,
                   help="Times to send failing tests back to the model for fixing (0 disables)")
    r.add_argument("--timeout", type=int, default=180)
    r.add_argument("--headed", action="store_true", help="Show the browser")
    r.set_defaults(func=cmd_run)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
