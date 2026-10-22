# AI QA Agent (MVP)

Inspects a target page, asks a Meta Llama model for test cases, generates a pytest + Playwright script,
vets it with a static safety check, then runs it against a local demo login app and writes a report.

```
inspect page -> Llama: test cases -> Llama: Playwright script -> safety check (+ repair loop) -> pytest run -> report.md
```

## 1. Meta Llama API access

1. Request access at the Llama API platform with your Meta account (access has been waitlisted and US-only; confirm current availability in Meta's Llama API docs).
2. Create an API key in the dashboard.
3. Copy `.env.example` to `.env` and set `LLAMA_API_KEY`. Keep `LLAMA_BASE_URL=https://api.llama.com/compat/v1/` (the trailing `/compat/v1/` matters).
4. If your account lists a different model ID, set `LLAMA_MODEL` accordingly (`python -m qa_agent check-api` prints available models).

No key yet? Use `--offline` to exercise the whole pipeline with built-in cases.

## 2. PyCharm on Windows setup

1. Open the folder in PyCharm. `File > Settings > Project > Python Interpreter > Add Interpreter > Virtualenv (.venv)`.
2. In the PyCharm Terminal (PowerShell):
   ```
   pip install -r requirements.txt
   playwright install chromium
   copy .env.example .env
   ```
3. Edit `.env` and add your key. `.env` is git-ignored.

## 3. Run it

```
python -m qa_agent check-api                       # verifies Meta API access
python -m qa_agent run --offline --start-demo      # no model, proves the pipeline works
python -m qa_agent run --start-demo                # real Meta model generates cases + script
python -m qa_agent run --start-demo --headed       # watch the browser
python -m pytest                                    # the project's own unit tests
```

Each run writes `out/<timestamp>/` with `cases.json`, `test_generated.py`, `junit.xml`, `results.json`, `report.md`.
Demo app credentials: `demo` / `demo123` (`python -m demo_app.app` runs it standalone on port 5000).

## 4. Safety model

- Targets must be `localhost`/`127.0.0.1` unless you set `ALLOW_REMOTE_TARGET=1` for a system you are authorized to test.
- Generated code is parsed with `ast` before anything runs: only `re`, `pytest`, `playwright.sync_api` imports; no
  `eval`/`exec`/`open`/JS evaluation/route interception; any URL literal must match the target host.
  Violations are sent back to the model for up to 2 repair attempts, then the run aborts.
- Tests run in a subprocess inside `out/<run>/` with a timeout and with API keys/tokens stripped from the environment.
  This is a guard rail for an MVP, not a hardened sandbox: use a container/VM before running untrusted models or remote targets.

## 5. GitHub

```
git init
git add .
git status            # confirm .env is NOT listed
git commit -m "AI QA agent MVP"
git branch -M main
git remote add origin https://github.com/<you>/ai-qa-agent.git
git push -u origin main
```

Create the empty repo on github.com first (no README/.gitignore). If you ever committed `.env`, rotate the key.

## Layout

```
demo_app/app.py        Flask login app (target under test)
qa_agent/config.py     .env settings + local-target guard
qa_agent/llm.py        Meta Llama client (OpenAI-compatible) + JSON/code extraction
qa_agent/inspector.py  Scrapes real selectors from the target page
qa_agent/generator.py  Test-case and script prompts, safety repair loop
qa_agent/safety.py     AST-based static checks
qa_agent/runner.py     Demo app launcher + pytest executor + junit parsing
qa_agent/offline.py    Deterministic fallback (no model)
qa_agent/cli.py        Pipeline + CLI
tests/                 Unit tests for the safety checker and demo app
```
