# Parley — private AI agents that split anything fairly

**Handoff doc for Hacktoberfest Hack Day Raleigh (Sat Oct 31, 2026).** Whoever picks this up, human or Claude, should be able to continue from this file alone. Read section 0 first.

---

## 0. How to use this doc (read first)

**If you're a teammate continuing in your own Claude:** paste this whole file into a new chat (or save it as `PLAN.md` in the repo root for Claude Code), then send:

> You're helping my team build "Parley" at a hackathon. PLAN.md is the full spec. Projects are due at 2:45 PM. Check the STATUS checklist in section 1, then help me with: **[the task, e.g. "implement core/auction.py and its tests per section 7"]**. Follow the schemas and formulas in this doc exactly; don't redesign them.

**Ground rules**
- The formulas in section 7 are decided. Implement them; don't renegotiate them.
- Build everything to run in **mock mode** first (no LLM, deterministic agents). Turn Gemma on once the end-to-end flow works.
- Keep the STATUS checklist below up to date in the repo copy so the next person knows where things stand.

---

## 1. STATUS checklist (update as you go)

- [ ] Repo created, deps installed, `GEMINI_API_KEY` works with a Gemma 4 model (deps + key done; code is in Documents/Parley, no git repo yet)
- [ ] Maritime account + credits (`HACKNCSTATE`, Growth plan) set up
- [x] `core/models.py` + `scenarios/inheritance.json` (main demo)
- [x] `core/allocation.py` (classify items, credits)
- [x] `core/auction.py` (clock auction) + tests
- [x] `core/settlement.py` (buyout settlement, minimal transfers) + tests
- [x] `core/leakfilter.py` + tests
- [x] `agent/` service with mock mode (intake form, `/interest`, auction endpoints, `/attest`)
- [x] `orchestrator/` state machine + `/state`
- [x] `ui/index.html` big screen (feed, item cards, credit bars, settlement, reveal)
- [x] End-to-end run in mock mode
- [x] Gemma turned on (strategy, comments, juror explanations, appraiser): `gemma-4-26b-a4b-it`, thinking minimal (~1 s/call); full inheritance run ≈ 55 s
- [ ] At least one agent running on Maritime (ideally all) — Dockerfile + steps in `parley/MARITIME.md`; needs a GitHub repo + Maritime account
- [x] Negotiation phase (P1)
- [x] `scenarios/roommates.json` (second scenario, shows it's general)
- [ ] Backup demo video recorded
- [ ] Slides done; project submitted on the MLH page (by 2:35)

---

## 2. Context

**Event:** 4h15m of hacking, 10:30 AM to 2:45 PM. Judging 2:45 to 3:45. Teams of 2–4.

**Prize tracks we're targeting (all three at once):**
| Track | How we qualify |
|---|---|
| Best Use of Gemma 4 | Every LLM call goes to Gemma 4 via the Gemini API |
| Best Open-Source AI Project | Gemma 4 is open-weight. Pitch angle: the model could run somewhere neither party has to trust |
| Best Use of Maritime | Each participant's agent is its own persistent Maritime micro-VM holding that person's secrets. Separate deployment per person *is* the architecture |

**Judging rubric**
- Relevance & Problem Definition: yes/no (do we meet the track requirements?)
- Impact & Value: 1–5
- Innovation & Creativity: 1–5
- Feasibility & Scalability: 1–5
- Technical Execution: 1–5 (does the prototype work and show a real technical concept?)
- Demo & Communication: 1–5 (goal, purpose, **limitations, next steps**, all explained concisely)

---

## 3. The product

**One-liner:** *Everyone gets a private AI advocate. The advocates negotiate and bid in a blackbox, a juror checks the result is provably fair, and you get a split nobody can call rigged, without anyone revealing their secrets.*

**Two pillars**
1. **Privacy.** Each person's preferences live only inside their own agent's VM. Agents never state their limits (enforced by a code-level leak filter). Fairness checks are done by each agent privately and reported back only as pass/fail.
2. **Fairness.** Contested items are settled by a budget-capped clock auction that works like a second-price auction, and payments are a simple "winner buys out the other owners' shares." Each agent then checks privately that it got at least its proportional share by its own valuation.

**General purpose:** the engine splits any pool of co-owned items. A "scenario" is just a JSON file of participants and items with ownership shares.

| Use case | What's being split |
|---|---|
| **Inheritance (main demo)** | A parent's belongings: heirlooms, car, furniture; specific bequests locked by the will |
| Roommates moving out (second demo scenario) | Couch, TV, kitchen appliances, cookware, table; some bought jointly, some by one person |
| Divorce | Household items, car, pets (non-money assets) |
| Startup or club breakup | Equipment, domain names, IP, leftover inventory |
| Group trip / shared purchases | Leftover gear, Costco haul, shared electronics |
| Lab or office moving | Monitors, chairs, equipment among teams |

Rent splitting by room (the scenario in Ritvik's earlier chat) is a stretch mode, see appendix A.

---

## 4. User flow

1. **Setup.** The executor (or whoever is organizing) loads a scenario: participants and items with market value and ownership shares. For an estate, every heir usually has an equal share and the will may lock some items to specific people. For roommates, shares follow who paid for what.
2. **Appraise (helper agent).** The Appraiser fills in a resale value for each item from purchase price, age and description, with a source and confidence. A human can override.
3. **Private intake.** Each person opens **their own agent's URL** on their phone and rates every item **0–10** ("how badly do you want it"):
   - 0 = won't take it, 1–4 = meh, 5–6 = want, 7–10 = really want.
   - Optional: a private max price per item, and a private reason ("Mom taught me to play on this piano").
   - Limit: at most three items rated 9–10.
   - These numbers never leave the agent's VM.
4. **Public interest buckets.** Each agent publishes only a coarse bucket per item: `NONE` (0–4), `WANT` (5–6), `STRONG` (7–10). This is the only preference info anyone else sees before the reveal.
5. **Easy allocation.** Items with no real conflict go straight to the person who wants them, at market value (they buy out the other owners' shares). Items nobody wants go to the **unwanted pile** (sell or donate, proceeds split by ownership).
6. **Negotiation (P1, optional).** For contested items, agents trade structured proposals for up to 4 rounds. If everyone accepts, that's a candidate deal.
7. **Bidding war.** Any item still deadlocked goes to a budget-capped clock auction among the people who want it.
8. **Juror.** It collects private pass/fail attestations from every agent, picks the final outcome and writes plain-English explanations.
9. **Reveal.** After the verdict, the agents release their secret inputs so everyone can check that nobody was pushed past their limits.

---

## 5. Architecture

```
                 ┌──────────────── ORCHESTRATOR (FastAPI) ────────────────┐
 phones ──┐      │ state machine · public catalog · event feed · auction  │
          │      │ clock · settlement · Juror · Appraiser                 │──► big-screen UI
          ▼      └───────▲──────────────────▲──────────────────▲──────────┘
  ┌──────────────┐       │ HTTP             │                  │
  │ Agent: Ana   │───────┘     ┌────────────┴──┐       ┌───────┴───────┐
  │ (Maritime VM)│             │ Agent: Ben    │       │ Agent: Cara   │
  │ private prefs│             │ (Maritime VM) │       │ (Maritime VM) │
  └──────────────┘             └───────────────┘       └───────────────┘
        each agent: intake form, private values, leak filter, Gemma calls
```

- **Orchestrator** knows only public info: the catalog, interest buckets, proposals, auction drop events, attestations.
- **Agent service** (one per participant) holds private ratings, max prices and reasons; computes private values; decides bids; runs the leak filter; attests fairness.
- **Build order for agents:** define an `Agent` interface with two implementations, `LocalAgent` (a Python object in the same process) and `RemoteAgent` (HTTP client). Build and demo-test with `LocalAgent`, then deploy the service to Maritime and switch to `RemoteAgent`. Same code either way.
- **Maritime:** we don't know its exact API yet. Check the docs at maritime.sh right away for how to deploy a Python web service and get a public URL. **Fallback:** run three agent processes locally on ports 8001–8003 and put at least one on Maritime.

### State machine
`SETUP → APPRAISE → INTAKE → EASY_ALLOC → NEGOTIATE (skippable) → AUCTION → JUDGE → REVEAL`

---

## 6. Data model (`core/models.py`, pydantic)

```python
class Participant(BaseModel):
    id: str              # "alex"
    name: str
    agent_url: str | None = None   # None => LocalAgent

class Item(BaseModel):
    id: str              # "couch"
    name: str
    category: str        # furniture | kitchen | electronics | decor | other
    description: str = ""
    purchase_price: float | None = None
    age_years: float | None = None
    market_value: float | None = None   # filled by Appraiser or human
    value_source: str = ""              # "Gemma estimate", "manual", "depreciation formula"
    confidence: str = "low"             # low | medium | high
    shares: dict[str, float]            # owner id -> share, sums to 1.0
    locked_to: str | None = None        # e.g. specific bequest in a will

class Scenario(BaseModel):
    id: str
    title: str           # "Estate of Margaret Lee"
    participants: list[Participant]
    items: list[Item]
    contest_threshold: int = 7    # rating needed to contest an item
    topup_pct: float = 0.5        # extra spend allowed beyond credits, as fraction of credits
    max_top_ratings: int = 3      # max items rated 9–10 per person

# ---- private, lives only inside an agent ----
class PrivatePrefs(BaseModel):
    ratings: dict[str, int]                 # item id -> 0..10
    max_prices: dict[str, float] = {}       # optional
    reasons: dict[str, str] = {}

# ---- public ----
Interest = Literal["NONE", "WANT", "STRONG"]

class Outcome(BaseModel):
    item_id: str
    winner: str | None        # None => unwanted pile
    price: float              # clearing price (market value for easy items)
    method: Literal["easy", "negotiated", "auction", "locked", "unwanted"]

class Event(BaseModel):       # drives the live feed
    t: float
    kind: str                 # phase | message | filtered | bid | drop | win | verdict
    actor: str | None
    text: str
```

---

## 7. Algorithms (decided: implement exactly)

### 7.1 Private value (inside each agent)
```python
def private_value(market: float, rating: int, max_price: float | None) -> float:
    if rating == 0:
        return 0.0                      # refuses the item
    if max_price is not None:
        return max_price                # explicit private max wins
    return market * (0.5 + rating / 10) # 5 -> 1.0x market, 7 -> 1.2x, 10 -> 1.5x
```

### 7.2 Interest bucket (published)
`0–4 → NONE`, `5–6 → WANT`, `7–10 → STRONG` (i.e. `≥ contest_threshold`).

### 7.3 Classify each item (orchestrator, public info only)
```python
def classify(item, interest):           # interest: {pid: "NONE"|"WANT"|"STRONG"}
    if item.locked_to:
        return ("locked", [item.locked_to])
    strong = [p for p, b in interest.items() if b == "STRONG"]
    want   = [p for p, b in interest.items() if b == "WANT"]
    if len(strong) >= 2:
        return ("contested", strong)
    if len(strong) == 1:
        return ("easy", strong)
    if len(want) == 1:
        return ("easy", want)
    if len(want) >= 2:
        return ("contested", want)      # tie among WANTs
    return ("unwanted", [])
```
Easy and locked items: `Outcome(winner=p, price=item.market_value)`.

### 7.4 Auction credits (the team's formula, generalized)
"Valuation of conflicting items divided by the number of people", computed per contested item over that item's contestants:
```python
credits[p] = sum(item.market_value / len(contestants[item.id])
                 for item in contested if p in contestants[item.id])
spend_cap[p] = credits[p] * (1 + scenario.topup_pct)   # top-up fixes the "tie at the cap" edge case
```
Credits are a **spending limit**, not money handed out. Real money moves only in settlement (7.6). This keeps purchasing power equal, so whoever has the most money can't just buy everything.

### 7.5 Clock auction (one item at a time, highest market value first)
**The LLM sets the strategy, the code executes it.** This keeps the auction fast and reliable.
1. Orchestrator calls `POST /auction/start` on each contestant's agent with public info: item, market value, its remaining spend cap, the remaining contested items.
2. Each agent privately picks a **drop price**. Gemma suggests one considering its remaining budget and items. The code then clamps it:
   `drop = min(llm_suggestion, private_value(item), remaining_spend_cap)`.
   The agent stores it and returns only a public comment (leak-filtered).
3. The clock starts at `0.2 × market` and rises by `max(5, 0.05 × market)` per tick. Each tick, the orchestrator calls `POST /auction/tick {item, price}` on each active agent; the agent answers `stay = price <= drop` in code, with no LLM call.
4. The last agent remaining wins at the current price. If all remaining agents drop on the same tick: **tiebreak** → fewer contested items won so far → seeded coin flip shown on screen.
5. Deduct the price from the winner's remaining spend cap.

The result equals a **second-price auction**: the highest drop price wins and pays about the second-highest. That makes bidding your true value the best strategy, which is a good point for the pitch. The tick animation is there for the demo.

### 7.6 Settlement: "winner buys out the other owners' shares"
```python
def settle(outcomes, items, sold: dict[str, float] = {}):
    cash = defaultdict(float)                 # + receives, - pays
    for o in outcomes:
        if o.winner is None:
            continue
        it = items[o.item_id]
        for owner, share in it.shares.items():
            if owner == o.winner:
                continue
            # owners who weren't bidding are protected: paid at least market value
            p = o.price if owner in contestants.get(it.id, []) else max(o.price, it.market_value)
            cash[o.winner] -= share * p
            cash[owner]    += share * p
    for item_id, proceeds in sold.items():    # unwanted pile sold externally
        for owner, share in items[item_id].shares.items():
            cash[owner] += share * proceeds
    return cash
```
Then turn net balances into the **fewest transfers** (greedy: biggest debtor pays biggest creditor, repeat). Show it as "Alex pays Sam $83.33".

**Sanity check (inheritance example from earlier, equal 50/50 shares):** ring won by Ana at $7.5k (pays Cara $3.75k), coins won by Cara at $5k (pays Ana $2.5k), piano won by Ana at $3k (pays Cara $1.5k). Net: **Ana pays Cara $2.75k**. Write this as a unit test.

### 7.7 Fairness attestation (inside each agent, private)
```python
def attest(me, outcomes, cash, items, my_values):
    u    = sum(my_values[o.item_id] for o in outcomes if o.winner == me) + cash[me]
    prop = sum(items[o.item_id].shares.get(me, 0) * my_values[o.item_id] for o in outcomes)
    return {"proportional_ok": u >= prop - 0.01}
```
"I got at least my ownership share of everything, by my own valuation." The agent returns only the boolean. Optional: envy-free check for scenarios with equal shares.

**Be honest about the edge case:** if a loser hit their spend cap before their true value, their check can fail. The juror shows that openly instead of hiding it, and it's a strong Q&A answer.

### 7.8 Leak filter (from Ritvik's design; runs on every outgoing agent message and comment)
```python
BANNED = ["my max", "my limit", "most i'd pay", "most i would pay", "up to",
          "willing to pay", "my budget", "my rating", "rated it", "walk away", "drop price"]
NUM = re.compile(r"\$?\s?(\d[\d,]*(?:\.\d+)?)\s*(k)?\b", re.I)

def leaks(text: str, secrets: list[float], public: list[float]) -> bool:
    t = text.lower()
    if any(b in t for b in BANNED):
        return True
    for m in NUM.finditer(t):
        n = float(m.group(1).replace(",", "")) * (1000 if m.group(2) else 1)
        if n < 20:
            continue                       # ignore small numbers and ratings
        for s in secrets:                  # private values, max prices, drop prices
            if any(abs(s - pv) <= 0.03 * pv for pv in public):
                continue                   # secret equals a public market value -> not a leak
            if abs(n - s) <= 0.03 * s:
                return True
    return False
```
If a message leaks: regenerate up to 2 times, then send a canned line ("Let's keep this moving."). Emit a `filtered` event so the big screen flashes **"🛡️ message filtered."** That's visible proof that privacy is enforced in code, not just hoped for.

### 7.9 Juror
1. Candidates: the negotiated deal (if every agent accepted) and the auction result.
2. Call `POST /attest` on every agent for each candidate.
3. Pick a candidate where every attestation passes. Prefer the negotiated deal, since it's consensual. If neither fully passes, pick the one with more passes and say so clearly.
4. Gemma writes one short explanation per person from **public** facts only (what they got, prices, transfers, pass/fail).
5. Verdict screen: final allocation, minimal transfers, ✅/⚠️ per person, explanations.

---

## 8. Negotiation phase (P1: build only after the auction works end to end)

- Round-robin, max **4 rounds**. Each round, one agent proposes and the others respond. Proposers rotate.
- Proposals cover contested items only:
```json
{
  "type": "propose | counter | accept | reject",
  "from": "ana",
  "round": 2,
  "proposal": { "piano": {"winner": "ana", "price": 7200}, "coins": {"winner": "ben", "price": 7600} },
  "message": "The piano matters a lot to my client; she's happy to see Ben keep Dad's coins..."
}
```
- **Orchestrator validates** every proposal: only contested items, winners must be contestants, prices > 0. Invalid ones get bounced back.
- **Agent accept rule (code, then LLM):** run `attest()` on the deal (with settlement computed). If it fails → must reject. If it passes, the LLM may accept or hold out.
- Messages go through the leak filter.
- The UI shows messages as they happen, redacted to "Alex's agent proposed a deal covering 2 items." Full transcripts appear at REVEAL.
- Known limitation for Q&A: accept/reject patterns over many rounds can still leak information. Future work.

---

## 9. Gemma 4 usage

| Where | What Gemma does |
|---|---|
| Appraiser (orchestrator) | Estimates resale value from name, description, purchase price and age → `{value, confidence, reasoning}` |
| Agent `/auction/start` | Suggests a drop price given remaining budget and items (clamped by code), plus a one-line public comment |
| Agent negotiation | Writes proposals and persuasive messages based on the private reasons |
| Juror | Writes plain-English per-person explanations |
| Stretch | Gemma 4 multimodal: photograph the room → list the items |

**Client** (`agent/llm.py`, shared):
```python
from google import genai
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
MODEL = os.environ["GEMMA_MODEL"]   # check Google AI Studio for the exact Gemma 4 model id

def ask_json(prompt: str, retries: int = 2) -> dict:
    for _ in range(retries + 1):
        text = client.models.generate_content(model=MODEL, contents=prompt).text
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    raise ValueError("no JSON from model")
```
- Gemma models on the Gemini API may reject `system_instruction`. If you get an error, put the instructions at the top of the prompt.
- Ask for JSON in the prompt and parse it defensively. Don't rely on structured-output features.
- `LLM_MODE=mock` env var: every Gemma call returns a deterministic canned answer. Use it for tests and as a fallback demo.

**Draft prompts**

*Appraiser*
```
You estimate used resale value (e.g. Facebook Marketplace) in USD.
Item: {name}. Category: {category}. Description: {description}.
Bought for ${purchase_price}, {age_years} years ago.
Reply with JSON only: {"value": number, "confidence": "low|medium|high", "reasoning": "one sentence"}
```
Fallback if Gemma fails: `value = purchase_price × 0.8^age_years` (furniture) or `× 0.7^age_years` (electronics).

*Agent: auction strategy*
```
You are {name}'s private negotiating agent. Scenario: {scenario_title} ({scenario_kind}, e.g. an inheritance among siblings).
Your client's private ratings (0-10): {ratings}. Their reasons: {reasons}.
Item up for auction: {item} (market value ${market}). Rivals: {rivals}.
Items still to come: {remaining_items_with_market_values}.
Your remaining spending cap: ${cap}. Your client's private value for this item: ${value}.
Decide the highest price to stay in at, saving budget for items your client cares about more.
NEVER reveal any of these numbers or ratings in "comment".
Reply JSON only: {"drop_price": number, "comment": "one short, friendly public line"}
```

*Juror explanation*
```
You are a neutral juror explaining a final split to {name}. Use only these public facts:
{outcomes}, {transfers}, fairness check for {name}: {pass_or_fail}.
Write 2-3 warm, plain sentences: what they got, what they pay or receive, and why it's fair.
```

---

## 10. API endpoints

**Agent service** (`agent/service.py`, one per participant; `PARTICIPANT_ID`, `ORCH_URL` env vars)
| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Phone intake form (sliders 0–10 per item, optional max price, reason) |
| POST | `/prefs` | Store `PrivatePrefs` (memory plus local JSON file inside the VM) |
| GET | `/interest` | `{item_id: "NONE"|"WANT"|"STRONG"}` |
| POST | `/negotiate` | Public state in → proposal or response out (P1) |
| POST | `/auction/start` | Public auction info in → `{comment}`; stores private drop price |
| POST | `/auction/tick` | `{item_id, price}` → `{stay: bool, comment?}` |
| POST | `/attest` | `{outcomes, cash}` → `{proportional_ok}` |
| POST | `/unlock` | Orchestrator says the verdict is final |
| GET | `/reveal` | Private prefs, only after unlock |

**Orchestrator** (`orchestrator/app.py`)
| Method | Path | Purpose |
|---|---|---|
| POST | `/scenario/{id}` | Load a scenario JSON |
| GET | `/catalog` | Public items (agents fetch this) |
| POST | `/next` | Advance the state machine one phase |
| POST | `/run` | Run every remaining phase automatically (demo button) |
| GET | `/state` | Phase, items, outcomes, events, auction status, credits, verdict |
| GET | `/` | Serves `ui/index.html` |

---

## 11. Repo layout
```
parley/
  scenarios/roommates.json  inheritance.json
  core/models.py  allocation.py  auction.py  settlement.py  fairness.py  leakfilter.py
  agent/service.py  logic.py  llm.py  prompts.py  form.html
  orchestrator/app.py  juror.py  appraiser.py  agents.py   # LocalAgent / RemoteAgent
  ui/index.html            # vanilla JS polling GET /state every 500 ms
  tests/test_settlement.py  test_auction.py  test_leakfilter.py
  run_local.sh             # orchestrator :8000, agents :8001-8003
  requirements.txt         # fastapi uvicorn httpx pydantic google-genai pytest
```
Stack: Python 3.11+, FastAPI, httpx, pydantic, google-genai. The UI is a single static HTML file, no framework.

---

## 12. Demo scenarios

### Main demo: `scenarios/inheritance.json`

**"Estate of Margaret Lee."** Three adult siblings, Ana, Ben and Cara, are dividing their mother's belongings (fictional sample data, labeled as such on screen). Teammates play the siblings. Every heir has an **equal ⅓ share** of every item unless the will says otherwise. The house is being sold separately and its proceeds split equally, so it isn't part of the auction. Say that in one line on the setup screen.

The will (a short fictional text in the scenario JSON, shown on screen) says: *"My watercolor painting of the lake house goes to my daughter Cara. Everything else is to be divided equally among my three children."*

| Item | Market $ | Ownership | Secret ratings (Ana / Ben / Cara) | Expected path |
|---|---|---|---|---|
| Diamond engagement ring | 9,000 | ⅓ each | 9 / 2 / 10 | **Contested** Ana vs Cara |
| Coin collection (Dad's) | 7,000 | ⅓ each | 2 / 9 / 8 | **Contested** Ben vs Cara |
| Upright piano | 6,000 | ⅓ each | 10 / 8 / 1 | **Contested** Ana vs Ben |
| Watercolor painting | 4,000 | ⅓ each | any | **Locked** → Cara (specific bequest), no cash |
| 2018 Honda CR-V | 18,000 | ⅓ each | 3 / 7 / 4 | Easy → Ben buys out Ana and Cara at $6,000 each |
| Dining set | 2,500 | ⅓ each | 6 / 2 / 3 | Easy → Ana, pays Ben and Cara $833.33 each |
| Grandfather clock | 1,500 | ⅓ each | 4 / 3 / 2 | Unwanted → sell (~$1,200), split |
| China set | 800 | ⅓ each | 1 / 0 / 2 | Unwanted → donate |

Credits for the bidding war: Ana = 9,000/2 + 6,000/2 = **$7,500**, Ben = 7,000/2 + 6,000/2 = **$6,500**, Cara = 9,000/2 + 7,000/2 = **$8,000**. Spend caps are 1.5× those (topup_pct 0.5).

**Tune before the demo.** Run the full flow in mock mode with these ratings and adjust ratings or `topup_pct` until the result tells a good story: three real conflicts, each sibling wins one contested item, a few clear transfers, and ✅ for all three. The mock agent's drop price should keep some budget for later items it rates ≥ 7, otherwise whoever wins the first item runs out of budget for the rest. If an outcome shows the spending-cap edge case (⚠️ from the juror), keep a second rating set that triggers it on purpose for Q&A.

The ring auction (Ana vs Cara, both rate it 9–10) is the emotional centerpiece. Give both agents good private reasons ("Mom wore it every day," "She promised it to me when I got engaged") so the comments in the feed tell a story.

### Second scenario: `scenarios/roommates.json` (shows it's general)

**"Hillsborough St 3BR — lease ends Dec 15."** Roommates Alex, Priya and Sam. During the demo, switch to this scenario and hit run to show the same engine handles unequal ownership.

| Item | Market $ | Ownership | Secret ratings (A / P / S) | Expected path |
|---|---|---|---|---|
| Sectional couch | 600 | ⅓ each | 9 / 8 / 2 | **Contested** A vs P |
| Espresso machine | 350 | ⅓ each | 10 / 2 / 9 | **Contested** A vs S |
| Dining table + 4 chairs | 300 | ⅓ each | 2 / 9 / 8 | **Contested** P vs S |
| 55" TV | 250 | Sam 100% | 7 / 3 / 6 | Easy → Alex buys it from Sam at $250 |
| Stand mixer | 200 | Priya 100% | 3 / 10 / 0 | Easy → Priya keeps it, no cash |
| Cookware set | 150 | Alex ½, Priya ½ | 8 / 4 / 0 | Easy → Alex, pays Priya $75 |
| Rug | 120 | ⅓ each | 1 / 3 / 2 | Unwanted → sell ~$50, split |
| Air fryer | 60 | ⅓ each | 5 / 4 / 8 | Easy → Sam |
| Old vacuum | 0 | ⅓ each | 0 / 0 / 1 | Unwanted → donate |

Each scenario JSON should also carry the demo ratings (e.g. a `demo_prefs` block) so mock mode and the "auto-fill" button on the intake form can use them.

---

## 13. Big-screen UI (what the judges watch)

- **Top:** scenario title, phase progress bar (`Appraise → Intake → Easy → Negotiate → Auction → Verdict → Reveal`).
- **Left:** item cards with photo or emoji, market value and value source; a status chip (easy / contested / sold / winner name).
- **Center:** live feed (messages, 🛡️ filtered flashes, bids, drops, wins).
- **Auction view:** current item, price ticking up, a **credit bar per contestant** draining as they win.
- **Verdict:** final allocation, minimal transfers ("Alex pays Sam $83.33"), ✅ per person, juror explanations.
- **Reveal:** each person's secret ratings and max prices next to what they got and paid. The audience can check the math themselves.

---

## 14. Team split and timeline (it's ~11:50, due 2:45)

| Person | Owns |
|---|---|
| **A: engine** | `core/` (models, classify, credits, auction, settlement, fairness) + tests, orchestrator state machine |
| **B: agents** | `agent/` service, mock mode, Gemma client and prompts, leak filter, attest, negotiation (P1) |
| **C: UI** | `ui/index.html` big screen, `agent/form.html` phone intake, reveal screen |
| **D: infra + pitch** | Maritime deployment, appraiser, scenario JSONs, slides, demo script, MLH submission |

With 3 people, merge C into D and keep the UI minimal.

| Time | Goal / checkpoint |
|---|---|
| 11:50–12:10 | Everyone reads this doc. Repo up, keys tested, Maritime signup. A commits `models.py` and `inheritance.json` **first** so others can code against them |
| 12:10–1:15 | Build in parallel with mocks. **Checkpoint:** `pytest` passes for settlement and auction; one agent responds locally |
| 1:15–1:50 | **End-to-end in mock mode** on the big screen, then turn Gemma on |
| 1:50–2:10 | Agents onto Maritime (switch to `RemoteAgent`); negotiation phase only if everything else works |
| **2:10** | **Feature freeze.** Record a backup demo video |
| 2:10–2:35 | Slides; **submit on the MLH page by 2:35**; rehearse twice |
| 2:45 | Judging |

**Cut list if behind (cut in this order):** negotiation phase → roommates scenario → phone form (enter on a laptop) → Gemma appraiser (hardcode values) → all-agents-on-Maritime (keep at least one). **Never cut:** auction, settlement, verdict, reveal.

---

## 15. Demo script (3 minutes)

1. **Hook (20s):** "When a parent dies, families often fight over their belongings, and the fight is usually over the ring or the piano, not the money. Nobody wants to say out loud how much they care."
2. **Setup (20s):** Show Margaret Lee's estate: the items, their appraised values, and the will. The painting is already locked to Cara as a specific bequest.
3. **Private intake (30s):** Three teammates enter secret ratings on their phones as Ana, Ben and Cara. "These numbers never leave each sibling's own agent, which runs in its own Maritime VM."
4. **Run (60s):** Easy items resolve instantly (Ben takes the car and buys out his sisters). The bidding war runs on the ring, coins and piano: credit bars drain, agents comment, and a 🛡️ filter flash shows a blocked leak.
5. **Verdict (30s):** Final split, a few simple transfers, ✅ ✅ ✅ fairness checks, the juror's explanation to each sibling.
6. **Reveal (20s):** Show the secret inputs next to what each sibling got. "Nobody paid more than their limit, and the will was followed."
7. **It's general (10s):** Switch to the roommates move-out scenario and run it.
8. **Close (10s):** Limitations and next steps slide, including "a mediation aid, not legal advice."

---

## 16. Pitch slides (5–6 slides)
1. Problem: splitting shared things is awkward, unfair and slow, and it's worst when a family divides an inheritance. The same problem shows up for roommates, divorces and business breakups.
2. Insight: give everyone a private advocate, with privacy and fairness enforced in code.
3. How it works: the architecture diagram, the auction and the buyout settlement.
4. Live demo.
5. Tracks: Gemma 4 everywhere; open weights → neutral, trustless hosting; Maritime = one VM per person.
6. **Limitations and next steps** (this is scored):
   - Limitations: sample data, Gemma-estimated values, spending caps can break the proportional guarantee (the juror reports it), info can leak via accept/reject patterns over many rounds, not legal advice.
   - Next: rent-by-room mode, photo-to-inventory, Venmo/Splitwise settlement export, real resale-price APIs, mediator dashboard for estates and divorces.

## 17. Q&A prep
- **"Why agents and not just an algorithm?"** Agents turn messy human preferences and reasons into strategy and explanations. They negotiate trades the algorithm alone wouldn't find. The algorithm is the safety net that guarantees fairness.
- **"Can't someone lie about their ratings?"** Ratings set your bid ceiling, so overstating means paying more. Ratings cost nothing to give; bids cost real money. And the auction works like a second-price auction, where bidding your true value is the best strategy.
- **"Can the orchestrator see my secrets?"** No. It sees only interest buckets, drop events and pass/fail checks. The full reveal happens only after the verdict.
- **"Is this legal advice?"** No. For estates or divorces it's a mediation aid that prepares a proposal for a professional to sign off on.
- **"Does it scale?"** It's one VM per participant and the clock auction is linear per item. Any group, any item list.

---

## Appendix A: Rent-by-room mode (stretch, from Ritvik's chat)
Rooms are items that must all be assigned, with prices summing exactly to the total rent `R`.
1. Each person privately values every room (their max for it; ideally their values sum to R).
2. Brute-force the assignment that maximizes total value (3–4 people means at most 24 permutations).
3. `surplus = (Σ assigned values − R) / n`. Each room's price = `winner's value − surplus`. Prices sum to R, and every person gets the same surplus.
4. If the total assigned value is less than R, no deal is possible within everyone's limits. Show "no deal," which is a legitimate outcome.
Use the same agents, leak filter and reveal screen. Only the solver differs.

## Appendix B: Hackathon logistics
- MLH check-in code: `8BXLXQTA` (mlh.com/checkin). Submission via the MLH submission page (QR code in the opening slides).
- Maritime: sign up at maritime.sh → maritime.sh/billing → subscribe on Growth → promo code `HACKNCSTATE`.
- Free partner credits: hacktoberfest.com/my/promos.
- Gemma 4 track info: mlh.link/Gemma. Open-source AI track: mlh.com/opensource-ai.
