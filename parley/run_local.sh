#!/usr/bin/env bash
# Parley local run: orchestrator on :8000, one agent process per participant on :8001-8003.
# Usage: ./run_local.sh [scenario]      (default: inheritance; LLM_MODE=mock unless .env has Gemma set)
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] || { python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt; }
PY=.venv/bin/python
export SCENARIO="${1:-${SCENARIO:-inheritance}}"
HOST="${HOST:-0.0.0.0}"   # 0.0.0.0 so phones on the same Wi-Fi can open the agent forms

pids=()
cleanup() { kill "${pids[@]}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

# AGENT1_URL / AGENT2_URL / AGENT3_URL point a slot at a remote agent (e.g. on Maritime);
# slots without one get a local agent process on :800N.
urls=()
for i in 1 2 3; do
  var="AGENT${i}_URL"
  if [ -n "${!var:-}" ]; then
    urls+=("${!var}")
  else
    AGENT_DATA_DIR=".agent_data/slot$i" $PY -m uvicorn agent.service:app --host "$HOST" --port "800$i" --log-level warning &
    pids+=($!)
    urls+=("http://localhost:800$i")
  fi
done
sleep 1.5
export AGENT_URLS="$(IFS=,; echo "${urls[*]}")"
$PY -m uvicorn orchestrator.app:app --host "$HOST" --port 8000 --log-level warning &
pids+=($!)
sleep 1.5
echo
echo "  Parley is up:  big screen  http://localhost:8000"
echo "                 agents      ${AGENT_URLS//,/  }  (phones: use this laptop's IP for localhost ones)"
echo "  LLM mode: $($PY -c 'from agent import llm; print(llm.MODE)')   scenario: $SCENARIO   (Ctrl-C to stop)"
wait
