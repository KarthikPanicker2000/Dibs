"""LLM client shared by agents and the orchestrator (PLAN.md section 9).

LLM_MODE picks the backend:
  mock   -> every call returns the caller's deterministic mock answer (tests, fallback demo)
  gemma  -> Gemma 4 via the Gemini API (the demo / prize track); needs GEMINI_API_KEY + GEMMA_MODEL
  claude -> the locally installed Claude Code CLI (`claude -p`) on its own login, no API key;
            for development and testing so Gemma quota isn't spent
Unset: gemma when GEMINI_API_KEY and GEMMA_MODEL are set, else mock.
Callers use ask_json_or(), which never raises: any failure returns the mock answer.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

log = logging.getLogger("parley.llm")


def _load_dotenv() -> None:
    """Tiny .env loader (parley/.env); real env vars win."""
    path = Path(__file__).resolve().parent.parent / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()

MODEL = os.environ.get("GEMMA_MODEL", "")
# Gemma 4 thinking: "minimal" (~1 s per call) or "high" (~8 s). Minimal keeps the live demo moving.
THINKING = os.environ.get("GEMMA_THINKING", "minimal")
_KEY = os.environ.get("GEMINI_API_KEY", "")
CLAUDE_BIN = os.environ.get("CLAUDE_BIN") or shutil.which("claude") or ""
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "haiku")

MODE = (os.environ.get("LLM_MODE") or ("gemma" if _KEY and MODEL else "mock")).strip().lower()
if MODE == "gemma" and not (_KEY and MODEL):
    log.warning("LLM_MODE=gemma but GEMINI_API_KEY/GEMMA_MODEL missing; using mock")
    MODE = "mock"
elif MODE == "claude" and not CLAUDE_BIN:
    log.warning("LLM_MODE=claude but the claude CLI isn't on PATH; using mock")
    MODE = "mock"
elif MODE not in ("mock", "gemma", "claude"):
    log.warning("unknown LLM_MODE=%s; using mock", MODE)
    MODE = "mock"
LABEL = {"mock": "mock mode", "gemma": "Gemma 4", "claude": f"Claude Code ({CLAUDE_MODEL}, dev)"}[MODE]

# Set after a failure that retrying won't fix soon (bad key, expired login): calls go straight to mock,
# with one retry a minute so a renewed login or key is picked up without a restart.
disabled_reason: str | None = None
_disabled_at = 0.0
RETRY_AFTER = 60.0
_FATAL = ("api key not valid", "api_key_invalid", "authenticate", "not logged in", "login", "permission_denied")

_client = None


def _gemma():
    global _client
    if _client is None:
        from google import genai
        from google.genai import types
        _client = genai.Client(api_key=_KEY, http_options=types.HttpOptions(timeout=30_000))
    return _client


def is_mock() -> bool:
    return MODE == "mock"


_config_ok = True


def _ask_gemma(prompt: str, image: Path | None = None) -> str:
    # Gemma on the Gemini API may reject system_instruction, so instructions live in the prompt.
    global _config_ok
    from google.genai import types
    contents = prompt
    if image is not None:      # Gemma 4 is multimodal: photo first, then the instructions
        mime = "image/png" if image.suffix.lower() == ".png" else "image/jpeg"
        contents = [types.Part.from_bytes(data=image.read_bytes(), mime_type=mime), prompt]
    if _config_ok and THINKING:
        try:
            cfg = types.GenerateContentConfig(thinking_config=types.ThinkingConfig(thinking_level=THINKING))
            return _gemma().models.generate_content(model=MODEL, contents=contents, config=cfg).text or ""
        except Exception as e:
            if "thinking" not in str(e).lower():
                raise
            _config_ok = False     # model doesn't take a thinking level; call it plainly from now on
    return _gemma().models.generate_content(model=MODEL, contents=contents).text or ""


def _claude_env() -> dict[str, str]:
    # Like a fresh terminal: no API keys (so the CLI uses its own login, not the API) and none of the
    # parent Claude Code session's variables, so the call is a standalone one-shot.
    return {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "ANTHROPIC_"))}


def _ask_claude(prompt: str, image: Path | None = None) -> str:
    tools, cwd = "", tempfile.gettempdir()
    with tempfile.TemporaryDirectory() as tmp:
        if image is not None:
            # copy the photo into a scratch folder and allow only the Read tool, scoped to that folder
            cwd = tmp
            shutil.copy(image, Path(tmp) / f"item{image.suffix.lower()}")
            prompt = f"Look at the photo in ./item{image.suffix.lower()} (use the Read tool).\n" + prompt
            tools = "Read"
        cmd = [CLAUDE_BIN, "-p", "--model", CLAUDE_MODEL, "--tools", tools, "--strict-mcp-config",
               "--no-session-persistence", "--output-format", "text"]
        if tools:
            cmd += ["--allowedTools", tools]
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=120, cwd=cwd, env=_claude_env())
    if r.returncode != 0:
        raise RuntimeError(f"claude -p failed: {(r.stderr or r.stdout).strip()[-300:]}")
    return r.stdout


def ask_text(prompt: str, image: Path | None = None) -> str:
    return _ask_claude(prompt, image) if MODE == "claude" else _ask_gemma(prompt, image)


def ask_json(prompt: str, mock: dict, retries: int = 2, image: Path | None = None) -> dict:
    if is_mock():
        return dict(mock)
    for _ in range(retries + 1):
        text = ask_text(prompt, image) if image is not None else ask_text(prompt)
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    raise ValueError("no JSON from model")


def ask_json_or(prompt: str, mock: dict, image: Path | None = None) -> tuple[dict, str]:
    """Never raises. Returns (answer, source): source is MODE ('gemma'/'claude'), 'mock' or 'fallback'."""
    global disabled_reason, _disabled_at
    if is_mock():
        return dict(mock), "mock"
    if disabled_reason and time.time() - _disabled_at < RETRY_AFTER:
        return dict(mock), "fallback"
    try:
        ans = ask_json(prompt, mock, image=image)
        disabled_reason = None
        return ans, MODE
    except Exception as e:  # network, quota, bad JSON, expired login: keep the demo moving
        msg = str(e)
        if any(f in msg.lower() for f in _FATAL):
            disabled_reason, _disabled_at = msg[:200], time.time()
            log.error("%s unusable, switching to mock answers: %s", LABEL, disabled_reason)
        else:
            log.warning("%s call failed, using fallback: %s", LABEL, msg[:200])
        return dict(mock), "fallback"
