"""One LLM call to check the configured backend: .venv/bin/python check_llm.py"""
import time

from agent import llm

print("LLM mode:", llm.MODE, "|", llm.LABEL)
if llm.is_mock():
    raise SystemExit("Mock mode. Set LLM_MODE=claude (dev) or GEMINI_API_KEY + GEMMA_MODEL (Gemma) in parley/.env.")
t = time.time()
print(llm.ask_json('Reply with JSON only: {"ok": true, "greeting": "one short hello"}', {}))
print(f"OK in {time.time() - t:.1f}s")
