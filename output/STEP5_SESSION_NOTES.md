# Step 5 — COMPLETE (2026-07-30); religious-filter tightening applied (2026-07-30)

## Final state

- **2091/2106 institution rows remain** after removing 15 rows (11 unique domains) identified as
  religious institutions that had slipped past Filters 1-5 — see "Religious-filter tightening"
  below. All remaining rows still have a `resource_list_url` from the completed Step 5 pass (or an
  empty URL with a `resource_list_notes` entry explaining why none exists).
- `output/snapshot_2026-07-30_before_religious_filter_tightening.xlsx` preserves the pre-removal
  2106-row state for comparison.
- `output/step5_checkpoint.json` reflects the state before this removal (0 remaining domains at the
  time Step 5 finished) — re-run `scripts/step5_status.py` if a fresh checkpoint is needed.

## Religious-filter tightening (2026-07-30)

Filter 5 (`is_religious_institution` in `notebooks/01_pull_and_filter_institutions.ipynb`) was
tightened with two additions, and applied directly to the existing spreadsheet (no full API
re-run):

1. **`RELIGIOUS_NAME_PATTERN`** — a regex catching unambiguous religious-institution name phrases
   (seminary, yeshiva, talmudic, rabbinical, torah, bible institute/college, divinity school,
   etc.), analogous to the existing arts/music name pattern in Filter 4. Caught 11 rows across 7
   domains whose `accreditor_raw` in the Scorecard API only lists a regional accreditor (e.g.
   Southeastern Baptist Theological Seminary is actually ATS-accredited, but the API only returns
   SACSCOC for it).
2. **`reference/manual_religious_institution_overrides.csv`** — a curated list of 4 institutions
   (Regent University, Calvin University, Spertus College, Columbia International University) that
   are religious but have no matching name keyword at all, so no regex could catch them safely
   without false-positiving on secular institutions with similar names.

**15 rows removed** (11 unique domains): Yeshiva University, Women's Institute of Torah Seminary
and College, Hebrew Union College-Jewish Institute of Religion (both campuses), Moody Bible
Institute/Moody Theological Seminary, Southeastern Baptist Theological Seminary (all 3 rows), Union
Theological Seminary in the City of New York, Western Seminary, Regent University, Calvin
University, Spertus College, Columbia International University.

See `SKILL.md`'s Filter 5 section for the full rationale. If this list needs extending further, add
specific institutions to the manual override CSV rather than broadening the name pattern.

**Not yet acted on — arts-filter (Filter 4) false negatives, still in the list:**
- College for Creative Studies (ccsdetroit.edu)
- Pratt Institute (pratt.edu)
- Cooper Union for the Advancement of Science and Art (cooper.edu)

These likely passed because their name doesn't match the narrow `ARTS_MUSIC_NAME_PATTERN` regex
and/or `pct_visual_performing_arts` is null (grad-heavy or design-heavy programs not captured the
same way conservatories are).

**Pages needing a manual recheck** (site was down or bot-blocked during the search, so the
recorded URL is a lower-confidence fallback):
- ccsdetroit.edu (College for Creative Studies) — entire site was returning 500 errors
- walshcollege.edu (Walsh College) — site 403'd every automated fetch attempt

## Resource URL verification (2026-07-30)

Ran the new `resource-url-verification` skill against
`output/accredited_nonprofit_secular_institutions_unique_resource_urls.xlsx` (1781 unique URLs).
Wrote a new file, `output/accredited_nonprofit_secular_institutions_unique_resource_urls_checked.xlsx`,
with 7 new columns: `http_status`, `final_url`, `is_soft_404`, `soft_404_match_text`, `page_title`,
`checked_at`, `check_notes`.

Results (1781 total):
- **1136 HTTP 200**, of which **16 flagged as likely soft 404s** (page title/heading literally says
  "Page Not Found" or "404" — spot-checked all 16, every one looks like a genuine dead link, no
  false positives observed).
- **1120 clean 200s** (no soft-404 signal).
- **223 non-200 HTTP status**: 172 real 404s, 27 403s (likely bot-blocking or access-restricted),
  22 429s (rate-limited during the check itself — worth a re-run to confirm these aren't false
  failures), 2 500s, 1 redirect loop.
- **422 request failures** (mostly `ConnectionError` — DNS failures, refused connections, or sites
  that reset the connection for automated requests; some may be transient/bot-blocking rather than
  truly dead — worth a slower re-check with lower concurrency for these specifically if a cleaner
  signal is needed).

So roughly 645 of 1781 URLs (36%) did not come back clean on this pass. A meaningful chunk of that
(the 429s and some ConnectionErrors) may be this check's own concurrency/rate triggering
anti-bot defenses rather than genuinely broken links — worth a slower, lower-concurrency re-run
targeted at just the non-OK rows before treating this as a final "broken link" list.

### Follow-up recheck pass (2026-07-30)

Added a second section to the same notebook: rechecks only the non-200 rows from the first pass,
at much lower concurrency (6 workers vs. 15) with a shorter per-request timeout (12s) but a retry
policy that specifically backs off on 429s (which the fast first pass doesn't). Wrote a new file,
`output/accredited_nonprofit_secular_institutions_unique_resource_urls_checked_rechecked.xlsx`,
adding `was_rechecked` and `http_status_before_recheck` columns so it's visible exactly which rows
were touched and what changed.

Of 640 rows rechecked: **18 flipped to a clean HTTP 200** — all but 2 of those were 429s on the
first pass (e.g. Princeton, Penn State Mont Alto, Arkansas State, UT Knoxville, Michigan Tech),
confirming the hypothesis that the fast pass's own concurrency was triggering rate-limiting on some
sites rather than those links being dead. The remaining **622 stayed non-200** on the slower recheck
(418 ConnectionError, 172 real 404, 27 403, 16 confirmed soft-404s, 2 500s, 2 SSLError, 1 redirect
loop) — these are much more likely to be genuinely broken or genuinely access-restricted.

One implementation note for whoever extends this further: the first version of the recheck cell
gave connection-level failures (dead/unresponsive hosts) the same large retry budget as HTTP-level
429/5xx responses, which made it try up to 4 times at a 25s timeout for hosts that were never going
to respond — that timed out an entire notebook-execution run after 40 minutes. Fixed by capping
`connect`/`read` retries to 1 in `make_session()` while keeping a larger `status` retry budget (for
429/502/503/504 specifically) with backoff — a dead host now fails in a couple seconds instead of
tying up a worker for over a minute.

## NDE backlink check (2026-07-30)

Ran the new `nde-backlink-check` skill against all 1,143 eligible (HTTP 200, non-soft-404) rows in
`output/accredited_nonprofit_secular_institutions_unique_resource_urls_checked_rechecked.xlsx`.
Wrote a new working file,
`output/accredited_nonprofit_secular_institutions_unique_resource_urls_checked_rechecked_with_nde_backlinks.xlsx`,
adding `has_nde_backlink`, `nde_backlink_source_url`, `backlink_check_notes`, `backlink_checked_at`.
Completed in a single ~4-minute run (8 workers, checkpointing every 10 rows) — didn't actually need
a resume across multiple sessions this time, but the design supports it if a future re-check of a
larger or slower set does.

Result: **only 1 of 1,143 resources has a confirmed NDE backlink** — Rush University's library A-Z
databases page (`https://library.rush.edu/az/databases`), which links directly to
`https://data.niaid.nih.gov/` (verified by hand, it's a real Springshare-tracked outbound link, not
a false positive). Verified the candidate-link-following logic itself works correctly (unit-tested
separately against synthetic HTML) — the zero-candidate result on nearly every other page reflects
that almost no institution currently lists "NIAID Data Ecosystem" (or similar wording) by name in
their library's database catalog, not a bug in the check.

Breakdown of the other 1,142: 638 rows were skipped (their source link isn't valid, so never
searched), 1,132 were checked with nothing found (no direct mention, no same-domain link whose
visible text mentioned NIAID/NDE/"data ecosystem" to follow), and 10 had a transient fetch error
during this specific check (worth a re-run of just those 10 via `check_nde_backlinks.py` — it'll
only reprocess rows without a note, so this is cheap).

Reminder of this skill's known scope limit (see its SKILL.md): it only follows same-domain links
whose *visible link text* references NIAID/NDE/"data ecosystem" — an NDE reference that exists on a
site but is reachable only via a differently-worded link, or more than one hop deep, would read as
"not found" here. Worth a manual spot-check if a specific institution is suspected to already
reference NDE despite a "not found" result.

## File renames (2026-07-30)

Shortened `resource-url-verification`'s output filenames (now fixed, not derived from the input
filename) and switched `nde-backlink-check` to a dated filename. Earlier entries in this log refer
to the old names, which are no longer accurate paths on disk — historical descriptions above are
otherwise unchanged. Renamed in place (content untouched, `check_nde_backlinks.py`/`.status.py`'s
own logic reflects the same eligibility results either way):

| Old name | New name |
| --- | --- |
| `accredited_nonprofit_secular_institutions_unique_resource_urls_checked.xlsx` | `unique_resources_checked.xlsx` |
| `accredited_nonprofit_secular_institutions_unique_resource_urls_checked_rechecked.xlsx` | `unique_resources_double_checked.xlsx` |
| `accredited_nonprofit_secular_institutions_unique_resource_urls_checked_rechecked_with_nde_backlinks.xlsx` | `2026-07-30_unique_resources_backlink_check.xlsx` |

Going forward, `resource-url-verification` always refreshes its two fixed-name files in place on
re-run; `nde-backlink-check` writes a new dated file whenever run on a new day (see its SKILL.md).

## How to re-run or extend

- To re-run Steps 1-4 (e.g. after updating the reference accreditor lists), see the main workflow
  in `SKILL.md`.
- To spot-check or correct an individual row, use `scripts/update_resource_entry.py --unitid <id>`
  (or `--domain <base_domain>` to update every row sharing that domain).
- `scripts/step5_status.py` will report "0 remaining" — keep it as a sanity check if the
  spreadsheet is ever regenerated or extended with new institutions.
