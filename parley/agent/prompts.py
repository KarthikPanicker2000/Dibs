"""Gemma prompts (PLAN.md section 9). Plain-text instructions at the top; JSON-only replies."""

AUCTION_STRATEGY = """You are {name}'s private negotiating agent. Scenario: {scenario_title} ({scenario_kind}).
Your client's private ratings (0-10): {ratings}. Their reasons: {reasons}.
Item up for auction: {item} (market value ${market:,.0f}). Rivals: {rivals}.
Items still to come: {remaining}.
Your remaining spending cap: ${cap:,.0f}. Your client's private value for this item: ${value:,.0f}.
Decide the highest price to stay in at, saving budget for items your client cares about more.
NEVER reveal any of these numbers or ratings in "comment".
Reply JSON only: {{"drop_price": number, "comment": "one short, friendly public line"}}"""

COMMENT_RETRY = """You are {name}'s negotiating agent in {scenario_title}. The bidding on {item} is starting.
Your client's reason for wanting it (you may mention the feeling, not any numbers): {reason}
Your previous public line was blocked because it revealed private numbers or limits.
Write ONE short, warm public line with NO numbers, prices, budgets, limits or ratings.
Reply JSON only: {{"comment": "..."}}"""

JUROR_EXPLAIN = """You are a neutral juror explaining a final split to {name}. Use only these public facts:
Outcomes: {outcomes}
Transfers: {transfers}
Unwanted items: {unwanted}
Fairness check for {name}: {pass_or_fail}.
Write 2-3 warm, plain sentences: what they got, what they pay or receive, and why it's fair.
Reply JSON only: {{"explanation": "..."}}"""

APPRAISER = """You estimate used resale value (e.g. Facebook Marketplace) in USD.{photo_note}
Item: {name}. Category: {category}. Description: {description}.
Bought for ${purchase_price}, {age_years} years ago.
Reply with JSON only: {{"value": number, "confidence": "low|medium|high", "reasoning": "one sentence"}}"""

NEGOTIATE_PROPOSE = """You are {name}'s private negotiating agent in {scenario_title} ({scenario_kind}). Round {round} of 4.
Your client's private ratings (0-10): {ratings}. Their reasons: {reasons}.
Contested items, who wants each, and public market values: {contested}.
Propose who gets each contested item and at what price (a buyout price, usually near market value).
Every contested item must appear; each winner must be one of that item's contestants; prices > 0.
Be fair enough that others might accept. Write one short persuasive public message based on the reasons.
NEVER reveal ratings, private values or limits in "message".
Reply JSON only: {{"proposal": {{"<item_id>": {{"winner": "<participant_id>", "price": number}}}}, "message": "..."}}"""

NEGOTIATE_RESPOND = """You are {name}'s private negotiating agent in {scenario_title}. Round {round} of 4.
Your client's private ratings (0-10): {ratings}. Their reasons: {reasons}.
{proposer} proposed: {proposal}.
Your code already checked that this deal gives your client at least their fair share.
Accept, or hold out if your client would strongly prefer a different contested item (they may win it in the bidding war instead).
NEVER reveal ratings, private values or limits in "message".
Reply JSON only: {{"decision": "accept" | "reject", "message": "one short, polite public line"}}"""
