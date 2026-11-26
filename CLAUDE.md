# Working in this repo (Claude)

Dummy money only. No bank, broker or demat link; the Upstox token is the read-only Analytics token. Never investment
advice. Merge only when the owner says "merge" (or "merge when ready"). Plan first, then ask before building.

## Workflow
- Discuss the outcome, give a short plan, then ask the owner to proceed. Don't build before "go".
- Show screenshots of every UI change (light and dark) before merging.
- Repo settings changes: tell the owner; the owner makes them. Checkov skips only with the owner's explicit OK.
- No after-tax P&L.
- After every review (monthly): (1) list one-off jobs, dry runs and retired code to clean up and remove only what
  the owner picks, (2) update the docs, (3) update the Stocks Platform Field Guide.
- The real pools (intraday, swing, long-term) are run by the AI inside the code limits in
  `docs/REBUILD_PLAN.md` section 3. The code limits change only at reviews. The AI may tighten, trail or exit a
  stop; it may never widen one. Shadows are rule-based paper tests and never touch a real trade.

## Isolation from the old repos
- Every resource is named `upx-` (SSM: `/upx/`). Nothing may read or write a resource owned by `paper-trader` or
  `stocks_lakehouse`; `scripts/check_isolation.py` runs in CI. The one-time copy job marks its lines `# isolation-ok`.

## Code: smallest complete change (ponytail rules)
- Read the task and the code it touches. List every place the change must reach: callers, tests, fixtures,
  config, infra, docs. That is the scope; extra features are not.
- Take the first option that fully works: not needed at all > already in this codebase > standard library or
  platform feature > an installed dependency > one clear line > the minimum code that works. Never add a
  dependency for a few lines.
- No abstraction, option, config or "for later" code nobody asked for. Deletion beats addition. Keep the
  existing structure and conventions.
- Finish everything the change breaks (callers, tests, fixtures, Terraform, docs).
- Bug fix: find every caller first, fix the root cause once in the shared code.
- New non-trivial logic (a branch, a loop, a parser, money, risk or security) gets a small test, written first.
- A shortcut with a known limit gets a comment: `shortcut: <the limit>, <when to upgrade>`.
- Never cut: validation at trust boundaries, error handling that prevents data loss, security, the risk gate.
- End the PR description with one line on what was skipped or not checked.

## Writing
Commits, PRs, docs and code comments: plain, complete English for a non-specialist owner.

## Replies to the owner
Answer precisely to the question. Next action first, numbered steps, short. Full sentences for questions and
warnings. No preamble or closers.

## App style
₹ sign; dates as "25 Nov"; no "since 18 Nov" text; Groww-style ‹ › column switches; folded "Legend (n)" on every
multi-line chart (tap a name to highlight, tap the chart to read values); top 5 + "Show all"; ★ = best shadow,
one note at the end of the tab; no instruction text on widgets unless really needed; light and dark themes.
Telegram messages carry no "[MOCK]" prefix; the bot's name and description say paper trading.

## Running the checks
- Tests: `python -m unittest discover -s tests -t .`
- Isolation: `python scripts/check_isolation.py`
