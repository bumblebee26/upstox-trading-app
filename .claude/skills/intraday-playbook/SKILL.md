---
name: intraday-playbook
description: How the paper trader's AI trades NSE intraday (dummy money) - objective, cycle, setups, candle and chart reading, volume, news reactions, stops and exits. Use in the trading session and when reviewing why the AI took or skipped a trade.
---

# Intraday playbook (paper trading, dummy money; never investment advice)

## Objective
The highest **net** P&L for the day after Upstox charges and slippage, flat by 15:10. A day with no trade is
fine; a forced trade is not. Protect the day first: one good trade beats five average ones.

## What code already does (don't fight it)
- Quantity comes from your stop so every trade risks the same rupees (1% of the pool, less when India VIX is high).
- The risk gate refuses trades outside its limits (window 09:30-14:30, 5 open, 10 a day, sector caps, 4R daily
  loss limit, cool-off after 3 losses, R:R at least 1.5, costs at most 30% of the risk). A refusal is final.
- Stops are fired by code every minute; you may tighten or trail, never widen. 15:10 square-off is automatic.

## Each 5-minute cycle
1. `screen` once. Pick at most 3 names worth a look; call `get_facts` on them (more only for a clear reason).
2. A trade needs **three things lined up**: a setup on the 5-minute chart, the 15-minute and daily context not
   against it, and the market (Nifty, sector) not against it. Two of three is a pass, not a trade.
   For every name you read and don't take to `review_trade`, call `note_pass` with the reason in one line.
3. `review_trade` with your honest pros, cons, YES % and the condition that would prove you wrong (`invalid_if`).
4. Read the council. Weigh the skeptic's concrete objection most; a base rate from few trades is weak evidence.
   Then `place_trade` or `skip_trade` with one line why.
5. Manage open trades from their facts: trail behind structure, exit when `invalid_if` happens, take the gain
   when momentum fades at a level. Then `wait_for_next_candle`.

## Setups (5-minute chart, confirmed by the close, never mid-candle)
- **Opening range breakout** (5/15/30 min): close beyond the range with relative volume ≥ 1.5. Stop inside the range.
- **VWAP reclaim / loss**: close back over (under) VWAP after a test, volume rising. Stop beyond the test's extreme.
- **Previous day high / low break**: the first clean close beyond it; avoid if price already ran 2+ ATR.
- **Gap and go / gap fade**: a gap holding its first 15-minute range (go) or failing it with volume (fade).
- **First pullback in a trend**: price above a rising EMA 20 with ADX > 20, pulls back to EMA 9/20 or VWAP and
  prints a bullish candle (mirror for shorts).
- **Inside bar / NR7 breakout**: compression, then a close beyond it in the trend's direction.
- **Level reactions**: pivots, Camarilla H3/L3 (fade) and H4/L4 (break), value-area high/low and point of
  control, round numbers, 52-week high/low. A level is stronger when several line up.
- **Mean reversion**: RSI(2) under 5 or over 95 at a level, with the daily trend in your favour. Smaller target.

## Reading candles and charts
- Reversal candles (hammer, shooting star, engulfing, harami, stars, tweezers) matter only **at a level and after
  a move**. In the middle of a range they are noise.
- Continuation (marubozu, three soldiers or crows, flags, triangles) matters only with the trend and volume.
- Long wicks into a level show rejection; closes show acceptance.

## Volume and the tape
Relative volume is the fuel: breakouts on weak volume fail more often. A buy/sell quantity ratio far from 1 and
a widening spread warn of a thin book. Never chase a candle more than 1 ATR beyond your trigger.

## News reactions
Results, big orders, mergers, management changes, rating changes, regulatory action, pledges. Trade the
**reaction** (price and volume after the news), not the headline. A stock up 8% on results with fading volume
is late; a stock breaking out on results with rising volume is not. Regulatory or pledge news: shorts only, or skip.

## Time of day
09:15-09:30 watch only (the gate blocks entries). 09:30-11:00 the best breakouts. 11:30-13:30 lunch lull:
fewer, smaller ideas. After 14:30 no new entries; manage and take profits into 15:10.

## Never
Average down; widen a stop; trade on stale data; invent facts not in the packet or news; re-propose the same
setup on the same stock within 30 minutes; trade to "win back" a loss.
