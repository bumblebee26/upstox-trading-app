"""The full council for swing and long-term plans, after the /llm-council skill: four members answer on
their own, four reviewers rank the anonymous answers, and a chair (the trader, on Opus) makes the final plan.

About 9 Claude calls per pool per decision day; members and reviewers run in parallel (Sonnet), so it takes
a minute or two, which is fine after the close. The money limits are still enforced by code afterwards.
"""
import json
import random
import re
from concurrent.futures import ThreadPoolExecutor

from trader.council import run_claude

TIMEOUT_SEC = 180
LENSES = {
    "skeptic": "what makes this plan lose money: late entries, weak trends, crowded trades, events ahead",
    "technical": "the charts: trend, levels, volume, momentum and candle structure on daily and weekly frames",
    "fundamentals_news": "the businesses and the news: results, valuation, shareholding, filings and sector",
    "portfolio_risk": "the pool as a whole: concentration, sector overlap, cash, how the stops add up",
}
EMPTY = {"buys": [], "sells": [], "stops": [], "notes": ""}

_MEMBER = """[member] You are on a review council for a PAPER {pool} stock pool on NSE (dummy money).
Your lens: {lens} - {desc}. Answer on your own; don't aim for a consensus.
QUESTION: should the trader's plan below be carried out as it is? What exactly should change?
CONTEXT: {context}
PLAN: {plan}
Return under 250 words: ANSWER (1-2 sentences), REASONING (3-5 points), RISKS, CONFIDENCE (low/medium/high)."""

_REVIEW = """[review] Below are anonymous answers about a trading plan for a paper {pool} stock pool.
Judge them strictly on correctness, insight and usefulness.
PLAN: {plan}
{answers}
Return: for each response its strongest point and biggest flaw (one line each); RANKING best to worst as
letters; MISSED: anything important none of them said."""

_CHAIR = """[chair] You are the trader and chair for a PAPER {pool} stock pool on NSE (dummy money).
Objective: the highest profit per position over its holding period, after costs. Code enforces the money
limits (position caps, stops that may only tighten), so stay inside them.
Weigh arguments, not votes: a lone concrete objection can beat a majority. Fix any factual errors the
reviewers caught. Then give the FINAL plan as one JSON object and nothing else:
{{"buys": [{{"symbol", "stop", "target", "why"}}], "sells": [{{"symbol", "why"}}],
"stops": [{{"symbol", "new_stop", "why"}}], "notes": "<one sentence: what you changed and why>"}}
CONTEXT: {context}
YOUR FIRST PLAN: {plan}
COUNCIL ANSWERS (by lens): {members}
PEER REVIEWS: {reviews}"""


def _json(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    d = json.loads(m.group(0)) if m else None
    if not isinstance(d, dict):
        raise ValueError("no JSON plan")
    return {k: d.get(k) or ([] if k != "notes" else "") for k in EMPTY}


def review(pool, context, plan, runner=run_claude, timeout=TIMEOUT_SEC):
    """Run the council on `plan` and return {"members", "reviews", "final"} (final = the chair's plan)."""
    ctx, pl = json.dumps(context, separators=(",", ":")), json.dumps(plan, separators=(",", ":"))

    def ask(prompt, model="sonnet"):
        try:
            return {"text": runner(prompt, timeout, model)}
        except Exception as err:  # a member that fails is noted; the rest carry on
            return {"error": f"{type(err).__name__}: {str(err)[:120]}"}

    with ThreadPoolExecutor(len(LENSES)) as pool_:
        members = dict(zip(LENSES, pool_.map(
            lambda lens: ask(_MEMBER.format(pool=pool, lens=lens.replace("_", " and "), desc=LENSES[lens],
                                            context=ctx, plan=pl)), LENSES)))

    answered = [(lens, m["text"]) for lens, m in members.items() if "text" in m]
    random.shuffle(answered)  # reviewers see letters, never the lens names
    letters = "ABCDEF"
    block = "\n".join(f"<Response {letters[i]}>\n{text}" for i, (_, text) in enumerate(answered))
    with ThreadPoolExecutor(max(1, len(answered))) as pool_:
        reviews = list(pool_.map(lambda _: ask(_REVIEW.format(pool=pool, plan=pl, answers=block)), answered))
    key = {letters[i]: lens for i, (lens, _) in enumerate(answered)}

    chair = ask(_CHAIR.format(pool=pool, context=ctx, plan=pl,
                              members=json.dumps({k: v.get("text", v.get("error")) for k, v in members.items()}),
                              reviews=json.dumps([r.get("text", r.get("error")) for r in reviews])), model="opus")
    try:
        final = _json(chair["text"])
    except (KeyError, ValueError, json.JSONDecodeError):
        # No valid decision: keep only what lowers risk (sells and tighter stops), never new buys.
        final = dict(EMPTY, sells=plan.get("sells") or [], stops=plan.get("stops") or [],
                     notes="the chair gave no valid plan, so only sells and stop moves were kept")
    return {"members": members, "reviews": reviews, "letters": key, "final": final}
