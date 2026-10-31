# Dibs

Each person gets a private AI agent that holds their secret preferences. The agents negotiate and bid
for co-owned items, a juror checks that the result is fair, and nobody reveals their numbers until the
verdict. PLAN.md (one folder up) has the full spec.

## Run it

```bash
./run_local.sh                 # big screen http://localhost:8000, agents :8001-8003
./run_local.sh roommates       # start with the second scenario instead
.venv/bin/python -m pytest -q  # tests
```

On the big screen, use **Next phase** to step through the demo or **Run all** to play it automatically. The
**agent ↗** link next to each person opens that person's private intake form, which also works on a phone
on the same Wi-Fi if you open the big screen by the laptop's IP. Forms have an **Auto-fill demo** button.
Anyone who hasn't submitted ratings when the Easy phase starts gets their demo ratings automatically.

Scenarios (dropdown → Load):
- `inheritance`: Estate of Margaret Lee, the main demo. Negotiation deadlocks over the ring, then the bidding
  war runs: Cara gets the ring, Ben the coins, Ana the piano, Ben pays both sisters, ✅ ✅ ✅.
- `roommates`: unequal ownership. The agents agree on a deal in round 1, so there's no auction.
- `inheritance-edge`: for Q&A. Ben's spending cap runs out below his true value for the piano, and the juror shows ⚠️.

## Rooms and phones

- **Admin:** http://localhost:8000/admin has a join QR, the run controls (Next phase, Run all, Reset, human-bidding
  toggle), seat status, and a room editor for title, instructions, people, items, values, ownership %, will locks
  and sale prices. **Save & open room** writes `scenarios/room-<title>.json` and opens it.
- **Join:** phones scan the QR (on the admin page, or on the big screen during setup and intake), tap their name, and land on their
  own agent's page. The first phone claims the seat with a token; other devices can't read or change it.
  Phones must be on the same Wi-Fi as the laptop. Use a phone hotspot if the venue Wi-Fi isolates devices.
- **Phone page:** instructions, your ratings (locked once interest is published), live bidding (countdown,
  price, your limit, **Set my limit**, **Drop out now**) and your result (fairness check with your own numbers,
  what you get and pay, and which of your wants were met). The phone only talks to its own agent; the agent relays the
  public room state.
- **Manual bidding** (admin toggle): people press Drop out on their phones; a 10 s countdown before each item.
- **Clock speed:** 2 s between price steps normally, 3.5 s with manual bidding. Change it live on the admin page.
- `run_local.sh` starts 6 phone seats (`AGENT_SLOTS` to change).

## LLM backends

`LLM_MODE` in `.env` picks the backend. Check it with `.venv/bin/python check_llm.py`, then restart
`run_local.sh`. The badge in the header shows which backend is running and turns red if it's failing.
Any failure falls back to the deterministic mock answer, so the demo keeps going.

- `claude`, for development and testing: uses the Claude Code CLI installed on this Mac (`claude -p`)
  with its own login, no API key, so no Gemma quota is spent. It runs with no tools and none of the
  parent session's environment. `CLAUDE_MODEL` defaults to `haiku`. If you see "OAuth session expired",
  run `claude auth login` in a terminal; the servers retry once a minute, so no restart is needed.
- `gemma`, for the demo and the Gemma prize track: set `GEMINI_API_KEY`. `GEMMA_MODEL` defaults to
  `gemma-4-26b-a4b-it`. Thinking is set to `minimal` (about 1 s per call; a full run takes about 55 s).
  Set `GEMMA_THINKING=high` for slower, more deliberate answers (about 8 s per call).
- `mock`: offline and deterministic. pytest always uses it. One-off: `LLM_MODE=mock ./run_local.sh`.

The LLM does these jobs: picking a drop price and writing a public comment (`/auction/start`), writing
proposals and replies (`/negotiate`), writing the juror's explanations, and appraising items with no value
(the roommates scenario). Code always clamps the drop price to min(LLM suggestion, private value, spend cap),
and every outgoing line passes through the leak filter.

## What's mocked in mock mode

- Drop price: the agent splits its remaining cap across the contested items it still wants, by private value.
- Comments, proposals and juror text are templates built from the private reasons.
- For an item rated 10, the agent deliberately drafts one over-sharing line so the 🛡️ leak filter visibly blocks it.
- Appraiser: purchase price × 0.8^age (0.7^age for electronics), rounded to $10.

## Knobs

`TICK_DELAY` (default 2 s per price step), `MANUAL_TICK_DELAY` (3.5 s), `PHASE_PAUSE` (1.2 s between phases), `NEGOTIATE=0` (skip
negotiation), `AGENT1_URL`, `AGENT2_URL`, `AGENT3_URL` (use a remote agent for that slot, e.g. on Maritime; see MARITIME.md).

## Layout

`core/` holds the pure algorithms (classify, credits, clock auction, settlement, fairness, leak filter).
`agent/` is the per-person service (`logic.py` holds the private state, `service.py` is HTTP, `form.html` is the intake form).
`orchestrator/` has the state machine, the juror, the appraiser and `LocalAgent`/`RemoteAgent`.
`ui/index.html` is the big screen.
