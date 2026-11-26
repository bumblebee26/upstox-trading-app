"""The quick council for intraday trades: two independent Claude members and a base rate worked out by code.

- Skeptic: argues against the trade from the facts (the old single reviewer's role).
- Tape reader: judges the price action and volume.
- Base rate: how often this setup has worked here before, shrunk toward 50% while there is little history.
Members see only the facts and the gate's numbers, never the AI's own reasons, so they can't be talked round.
Each member's score is kept, so "skeptic alone" (the old reviewer) can still be compared with the council.
The full /llm-council (4 lenses, peer review, chair) is for swing and long-term decisions, not here.
"""
import json
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

TIMEOUT_SEC = 30
MODEL = "sonnet"

_ASK = """[{name}] You are one member of a trading review council for a PAPER trade (dummy money) on NSE.
{lens}
Judge only from the facts below. Answer with one JSON object and nothing else:
{{"yes_pct": <0-100, your chance this trade makes money after costs>, "verdict": "for"|"against"|"split",
"why": "<under 25 words>"}}

TRADE: {side} {symbol}  entry {entry}  stop {stop}  target {target}
GATE: {gate}
FACTS: {facts}"""

LENSES = {
    "skeptic": "Your lens: the skeptic. Look hardest for why this trade loses: a late or extended entry, weak "
               "volume, a nearby level against it, a market or sector moving the other way, costs.",
    "tape": "Your lens: the tape reader. Judge the price action and volume: is the move clean and supported, "
            "where are buyers and sellers, does the candle structure confirm the direction?",
}


def run_claude(prompt, timeout, model=MODEL):
    """One Claude call with no tools (it can only read and answer). Claude Code doesn't pass its own login to
    the tools it starts, so the session gives the same subscription token as COUNCIL_CLAUDE_TOKEN."""
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)  # bill the subscription, never an API key
    if env.get("COUNCIL_CLAUDE_TOKEN"):
        env["CLAUDE_CODE_OAUTH_TOKEN"] = env["COUNCIL_CLAUDE_TOKEN"]
    out = subprocess.run(["claude", "-p", prompt, "--model", model, "--tools", ""], capture_output=True,
                         text=True, timeout=timeout, check=True, env=env)
    return out.stdout


def _parse(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise ValueError("no JSON in the answer")
    d = json.loads(m.group(0))
    return {"yes_pct": max(5, min(95, int(round(float(d["yes_pct"]))))), "verdict": d.get("verdict", ""),
            "why": str(d.get("why", ""))[:200]}


def base_rate(track, setup):
    """Earlier real outcomes of this setup: (wins + 5) / (trades + 10), so 0 trades gives 50%."""
    rows = [t for t in track if t.get("setup") == setup]
    wins = sum(1 for t in rows if t.get("won"))
    return {"yes_pct": round((wins + 5) / (len(rows) + 10) * 100, 1), "n": len(rows), "verdict": "",
            "why": f"{wins} of {len(rows)} earlier {setup} trades made money"}


def review(case, track, runner=run_claude, timeout=TIMEOUT_SEC):
    """Ask the council about one trade. case: symbol, side, entry, stop, target, gate, facts (and the
    AI's reasons, which are never shown to members). Returns each member's answer and the average."""
    start = time.monotonic()
    shown = {k: case.get(k) for k in ("symbol", "side", "entry", "stop", "target")}
    gate = json.dumps(case.get("gate") or {}, separators=(",", ":"))
    facts = json.dumps(case.get("facts") or {}, separators=(",", ":"))

    def ask(name):
        try:
            return _parse(runner(_ASK.format(name=name, lens=LENSES[name], gate=gate, facts=facts, **shown), timeout))
        except Exception as err:  # a member that fails is left out, never guessed
            return {"error": f"{type(err).__name__}: {str(err)[:120]}"}

    with ThreadPoolExecutor(len(LENSES)) as pool:
        answers = dict(zip(LENSES, pool.map(ask, LENSES)))
    answers["base_rate"] = base_rate(track, case.get("setup"))
    scores = [a["yes_pct"] for a in answers.values() if "yes_pct" in a]
    yes = round(sum(scores) / len(scores), 1)
    votes = [a.get("verdict") for a in answers.values() if a.get("verdict")]
    return {"members": answers, "yes_pct": yes, "for": votes.count("for"), "against": votes.count("against"),
            "seconds": round(time.monotonic() - start, 1)}
