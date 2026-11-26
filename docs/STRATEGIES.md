# Strategy catalog (shadows: paper tests that never touch a real trade)

Dummy money only; nothing here is investment advice. Every shadow is listed here **before** it is built, with
exact rules, so results can't be tuned after the fact. Shadows are plain code with no Claude calls. Each one
keeps its own paper ledger; families and luck lines (PR 8) judge them: "too early" under 100 trades, the
**pass bar** at 200+ trades above the luck line and still above it in the weeks after.

Status: **built** = in code; **PR n** = planned in that pull request.

## 1. Intraday (built in PR 7)

**Common rules for every intraday shadow**
- Universe each day: Nifty 500 stocks that pass the screen's guardrails on the previous day's data (price ₹50+,
  ₹50 crore+ average daily turnover). Pool ₹40,000; risk 1% (₹400) a trade, sized from the stop; at most 5 open
  and 10 trades a day per strategy, one entry per stock per strategy per day.
- Signals are judged on **5-minute closes** from 09:30 to 14:30. The fill is the **next 1-minute open** plus
  0.05% slippage. Stops are checked on every 1-minute candle; if one candle touches both the stop and the
  target, the stop counts (the cautious reading). Everything still open closes at the 15:10 1-minute open.
- Costs: Upstox's own charges for each order (the same as the real pools). R:R at least 1.5 where a target exists.
- "Volume up" means the 5-minute bar's volume is at least 1.5x the average 5-minute volume so far today.

### 1a. Entries (each run with exit X1 unless listed)
| ID | Name | Long signal (shorts mirror it) | Stop |
|---|---|---|---|
| E01 | Opening range breakout 5 | Close above the 09:15-09:20 high, volume up | Range low (at most 1.5 ATR) |
| E02 | Opening range breakout 15 | Close above the 09:15-09:30 high, volume up | Range low (at most 1.5 ATR) |
| E03 | Opening range breakout 30 | Close above the 09:15-09:45 high, volume up | Range low (at most 1.5 ATR) |
| E04 | VWAP reclaim / loss | Previous close under VWAP, this close above it, volume up | Lowest low of the last 3 bars |
| E05 | Previous day high / low break | First close above yesterday's high | This bar's low |
| E06 | Gap and go | Gap up 1%+, first close above the 15-minute range high | 15-minute range low |
| E07 | Gap fade | Gap down 3%+ that closes back above the 15-minute range high before 11:00 (shorts: the old gap-up fade) | Day low |
| E08 | Opening drive | First 15 minutes up 1%+, closing in the top fifth of the range: enter at 09:30 | 15-minute range midpoint |
| E09 | First pullback | Close above a rising EMA 20 with EMA 9 above it; a bar touches EMA 9 or VWAP and closes up | That bar's low |
| E10 | Inside bar breakout | Close above the mother bar, EMA 20 rising | Mother bar low |
| E11 | NR7 day breakout | Yesterday was the narrowest of 7 days; close above yesterday's high | Yesterday's midpoint |
| E12 | Camarilla L3 fade | Low under L3, close back above it | L4 |
| E13 | Camarilla H4 break | Close above H4 | H3 |
| E14 | Pivot bounce | Low touches S1 (within 0.1%), close above S1 | 0.3% under S1 |
| E15 | RSI(2) extreme | 5-minute RSI(2) under 5 while the close is above the daily EMA 20; target VWAP (no R:R rule) | 1 ATR |
| E16 | EMA 9/20 cross | EMA 9 crosses above EMA 20 with ADX over 20 | This bar's low |
| E17 | Supertrend flip | Supertrend (10, 3) turns up | Supertrend line |
| E18 | Bollinger squeeze breakout | Band width in the lowest fifth of today's bars, then a close above the upper band | Middle band |
| E19 | Volume spike | Volume 3x average, close in the top quarter of the bar, bar up 0.5%+ | This bar's low |
| E20 | Strength vs sector | After 10:00, the stock is 1%+ ahead of its sector index since the open and above VWAP | VWAP minus 0.2% |
| E21 | Reversal candle at support | Bullish engulfing, hammer or morning star within 0.3% of yesterday's low, VWAP lower band, S1, L3 or the value-area low | Pattern low |
| E22 | Round-number break | Close crosses above a round number, volume up | This bar's low |
| E23 | Value-area break | After 10:30, close above today's value-area high | Point of control |
| E24 | Lag behind the index | Nifty up 0.5%+ since the open, the stock flat or down but above VWAP, close above the last bar's high | Day low |
| E25 | Fibonacci pullback | After a 1%+ morning move up, price pulls back to 61.8% of it and closes up | 78.6% level |
| E26 | Heikin-Ashi trend | Three green Heikin-Ashi bars with no lower wick, above EMA 20 | Third bar's low |
| E27 | Bull flag break | `bull_flag` (core/patterns.py) on 5-minute bars and a close above the flag high | Flag low |
| E28 | Triangle breakout | `triangle` on 5-minute bars, then a close above its high, volume up | Triangle low |
| E29 | Marubozu continuation | Bullish marubozu above VWAP with volume up | Bar midpoint |
| E30 | Three white soldiers | `three_white_soldiers` above EMA 20 | First soldier's low |

### 1b. Exit variants
| ID | Exit |
|---|---|
| X1 | Stop, or target at 2R (default) |
| X2 | Target at 1.5R |
| X3 | No target; from +1R the stop trails 1R behind the best price |
| X4 | Stop to breakeven at +1R, target 2R |
| X5 | Time stop: out after 60 minutes if the target isn't hit |
| X6 | Stop only, held to 15:10 |
| X7 | Out on the first 5-minute close back through VWAP |

Exit variants X2-X7 run on the four core entries E02, E04, E05, E09 (24 variants).

### 1c. Regime overlays (on E02, E04, E05, E09; 12 variants)
| ID | Only trade when |
|---|---|
| O1 | India VIX's previous close is under 20 |
| O2 | Longs: Nifty 50 above its 200-day average; shorts: below |
| O3 | Nifty 50 since the open is moving the same way as the trade |

**Intraday total: 30 + 24 + 12 = 66 variants.**

## 2. Swing (PR 8)
Common: pool ₹60,000; at most 7 holdings at 25%; buy at the next open, stop checked on closes; Upstox delivery
charges with the DP charge on sells; idle cash stays cash.

| ID | Name | Rule |
|---|---|---|
| S01 | Momentum + news (the old live rules) | Top momentum ranks (trader/rank.py), up for a fresh positive filing; stop 2 ATR, trail 2 ATR under the highest close; out after 20 days |
| S02 | 52-week-high breakout | Close at a new 52-week high on 1.5x volume; stop 2 ATR; trail 2 ATR |
| S03 | 20-day breakout (Donchian) | Close above the 20-day high; exit on a close under the 10-day low |
| S04 | Turtle 55-day | Close above the 55-day high; exit under the 20-day low |
| S05 | Pullback to EMA 20 | Uptrend (above EMA 50 and 200), close touches EMA 20 and turns up; stop under the swing low |
| S06 | Pullback to EMA 50 | As S05 at EMA 50 |
| S07 | RSI(2) mean reversion | Above EMA 200, RSI(2) under 10; exit when the close is above the 5-day average |
| S08 | Bollinger mean reversion | Above EMA 200, close under the lower band; exit at the middle band |
| S09 | MACD cross | MACD crosses above its signal while above EMA 50; exit on the opposite cross |
| S10 | Golden cross | EMA 50 crosses above EMA 200; exit on the opposite cross |
| S11 | Tight base (VCP-style) | Three narrowing pullbacks within 20% of the high, then a breakout on volume |
| S12 | Post-results drift | Gap up 3%+ on results that holds the first day; stop under the gap day's low |
| S13 | Delivery accumulation | Delivery % (NSE) above its 20-day average for 3 days while price rises (needs the NSE delivery file, PR 9) |
| S14 | Sector rotation | Buy the 2 strongest stocks of the 2 strongest sectors over 1 month; rebalance weekly |
| S15 | Relative strength rank | Top 7 by 3-month return relative to Nifty; rebalance weekly |
| S16 | News breakout (old shadow) | Filing within 2 days, close above the 20-day high on 2x volume, up 2%+, above EMA 50; stop 5-day low (at most 8%); target 2R; 10 days |
| S17 | Technical scanner (old shadow) | Above EMA 20/50/200, RSI 50-65, MACD above signal, ADX over 20 and rising, volume 1.5x, R:R 2+ |
| S18 | Concentrated momentum (old shadow) | Top 3 of S01 at 3% risk |
| S19 | Darvas box | New box above the last; buy the box breakout; stop the box low |
| S20 | Weinstein stage 2 | Close above a rising 30-week average after a base; exit under the average |
| S21 | Ichimoku | Close above the cloud with Tenkan over Kijun; exit under the Kijun |
| S22 | Elder triple screen | Weekly trend up (MACD histogram rising), daily RSI under 30 then turns up |
| S23 | Cup and handle / double bottom | Simple pattern checks on daily bars; buy the handle or neckline break |
| S24 | Insider and promoter buying, bulk and block deals | Promoter buying (NSE filings) or a known fund's bulk buy, with the price holding above it for 2 days (needs the NSE deals file, PR 9) |
| S25 | Long build-up in stock futures | Price and futures open interest both up 2 days in a row (information only; no futures trades) |

Exit variants for swing (on S01, S02, S05): chandelier exit (3 ATR under the highest high), parabolic SAR,
time stop at 10 days.

## 3. Long-term (PR 8)
Common: pool ₹1,00,000; at most 10 holdings, at most 15% each, at most 2 per industry; rebalance on the first
Saturday of the month unless noted; Upstox delivery charges.

| ID | Name | Rule |
|---|---|---|
| L01 | Quality (old shadow) | ROCE 15%+, debt under 0.5x equity, positive operating cash flow 3 of 4 years, 10%+ revenue and profit growth over 3 years, P/E in the cheaper half; top 10 |
| L02 | Momentum 30 (old shadow) | Top 15 by the Nifty Momentum 30 method, no loss-makers, debt under 1.5x outside banks |
| L03 | Concentrated momentum (old shadow) | Top 5 of L02 |
| L04 | Value | Lowest P/E among stocks with ROCE 15%+ |
| L05 | Growth at a reasonable price | PEG under 1 with profit growth 15%+ |
| L06 | Magic Formula | Rank by earnings yield plus return on capital; top 10 |
| L07 | Dividend yield | Top yields with a payout ratio under 70% |
| L08 | Low volatility | Lowest 1-year volatility among quality stocks |
| L09 | Quality + momentum | L01's list ranked by 6-month return |
| L10 | Shareholding changes | Promoter or FII holding up 1%+ over the last quarter |
| L11 | Coffee-can | 10 years of 10%+ revenue growth and ROCE 15%+ every year; buy and hold |
| L12 | Piotroski F-score | Score 8-9 of 9 |
| L13 | Altman Z distress filter | L01 minus companies with Z under 1.8 |
| L14 | Dividend growth | Dividend raised 5 years running |
| L15 | Equal-weight Nifty Next 50 | Hold all 50 equally; rebalance quarterly |
| L16 | Equal-weight Nifty 50 | Hold all 50 equally; rebalance quarterly |

## 4. Benchmarks (PR 8)
| ID | Benchmark | For |
|---|---|---|
| B01 | NIFTYBEES bought on day 1 and held | Swing and long-term |
| B02 | NIFTYBEES monthly SIP (equal amount on the first trading day of each month) | Swing and long-term |

## 5. AI-versus-rules split tests (PR 8)
Built from the AI's saved decisions, so they cost no Claude calls. They show where the AI adds value.
| ID | Test |
|---|---|
| A01 | The AI's real intraday entries with exit X1 (rules manage the exit) |
| A02 | The AI's real intraday entries with exit X3 |
| A03 | Rule entries E02, E04, E05, E09 with the AI's exits (when the AI managed a similar trade the same day) |

## 6. Carried from the old system
The old exit variants, opening-range tests and auto-bar ladder are covered by E01-E03 and X1-X7. The six old
shadow models (volatility stop, trade filter, early cut, let winners run, combined, skip stretched) and the
council test's old history come across with the lakehouse copy (PR 10) and keep their old results.
