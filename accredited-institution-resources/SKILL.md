---
name: accredited-institution-resources
description: Build a spreadsheet of U.S. institutions accredited by both the Dept. of Education (ED) and CHEA, limited to non-profit and non-religious institutions, with each institution's homepage and library/biomedical resources-list page URL. Use when asked to compile, refresh, or extend a list of accredited colleges/universities and their library resource pages.
---

# Accredited institution resource-page directory

Produces `output/accredited_nonprofit_secular_institutions.xlsx`: one row per U.S. institution that
is accredited by an accreditor recognized by **both** the U.S. Department of Education (ED/USDE) and
the Council for Higher Education Accreditation (CHEA), is **non-profit** (public or private
non-profit — not private for-profit), is **non-religious** (by IPEDS field, faith-related
accreditor, and theology-program share — see Filter 5), is **not a dedicated art/music school**
(scope is biomedical science — see Filter 4), plus its homepage URL and (once Step 5 is done) the
URL of its library/biomedical-discipline resources list page. Rows are **sorted by biomedical
program relevance** (highest first, see "Prioritize by biomedical relevance" below) rather than
alphabetically, so Step 5 tackles the most relevant institutions first.

## Data sources and why they're used this way

- **College Scorecard API** (`api.data.gov/ed/collegescorecard`) is the single source for Steps 1-4.
  Every institution it lists participates in Title IV federal student aid, which by definition
  requires accreditation from a USDE-recognized accreditor — so the ED-recognition requirement is
  already satisfied for anything returned by this API. It also exposes, per institution: primary
  accreditor name (`school.accreditor`), ownership/control (`school.ownership`), religious
  affiliation (`school.religious_affiliation`), and homepage URL (`school.school_url`) in one call.
- **CHEA dual-recognition check**: `reference/chea_usde_institutional_accreditors.csv` lists the
  institutional (regional) accreditors confirmed — via CHEA's own published chart,
  `CHEA-USDE_Recognized_Organizations.pdf` — to be recognized by both CHEA and USDE. As of the
  chart's May 2021 edition all seven institutional/regional accreditors (ACCJC, HLC, MSCHE, NECHE,
  NWCCU, SACSCOC, WSCUC) are dual-recognized. **This reference list can go stale** if CHEA
  adds/withdraws recognition of an accreditor — see "Keeping the reference list current" below.
- Direct `WebFetch` of chea.org pages returns HTTP 403 (bot-blocked). A plain HTTP request with a
  standard browser `User-Agent` header works fine, including for the PDF chart above — use that
  approach (`curl -A "Mozilla/5.0 ..."` or `requests` with a `User-Agent` header) if you need to
  re-fetch or verify against CHEA's site directly, rather than assuming WebFetch will work.
- **Rate limits**: the College Scorecard key's default tier is 1,000 requests/hour (confirmed live
  via the `X-Ratelimit-Limit`/`X-Ratelimit-Remaining` response headers), shared across all
  api.data.gov APIs using that key. The full institution pull is only ~63 requests
  (6,273 institutions ÷ 100 per page), so this limit is never realistically at risk, but
  `fetch_all_institutions()` in the notebook still paces requests at ~3.6s apart (a hard ceiling of
  1,000/hour even if run continuously), pauses if `X-Ratelimit-Remaining` drops near 0, and retries
  on 429 with backoff (respecting `Retry-After` when present) rather than failing the whole pull.
- **`academics.program_percentage.*` fields need a `latest.` prefix.** The bare
  `academics.program_percentage.X` alias silently returns `null` for every institution — verified
  live against the API (even Juilliard, ~100% performing arts, came back null). The correct path is
  `latest.academics.program_percentage.X` (`school.*` fields are top-level aliases and don't need
  this; `academics.*` fields are nested under `latest` in the raw response and do). This bug meant
  Filters 4 and 5's percentage-based checks silently did nothing for a while — only their
  name/accreditor fallback signals were ever doing real work — until it was caught while building
  the biomedical-relevance sort below and Juilliard turned up as a false negative.
- **`program_percentage` fields are computed from undergraduate completions only.** Standalone
  graduate/professional schools (verified: Albert Einstein College of Medicine, A T Still
  University of Health Sciences) have these fields null even though they're obviously biomedical —
  this is why biomedical relevance is a *sort*, not a filter (see below): a threshold filter would
  wrongly drop exactly the medical/health-professional schools most worth keeping.

## Workflow

### Steps 1-4: pull, filter, export (scripted, deterministic)

1. Get a free API key from https://api.data.gov/signup/ if one isn't already available. The
   notebook accepts it two ways, checked in this order:
   - **Environment variable** `COLLEGE_SCORECARD_API_KEY` — takes priority if set. This is the path
     for CI/automated runs: store the key as a GitHub Actions secret and expose it to the job as
     this environment variable (e.g. `env: COLLEGE_SCORECARD_API_KEY: ${{ secrets.COLLEGE_SCORECARD_API_KEY }}`
     in the workflow YAML). Nothing needs to be checked into the repo for this path.
   - **`credentials.json`** at the repo root (`resource_listings/credentials.json`) — the fallback
     for local/interactive use, read only if the environment variable above isn't set:
     ```json
     {
       "credentials": {
         "email": "you@example.com",
         "key": "your-api-key"
       }
     }
     ```
     This file is gitignored — never commit it.
2. Run `notebooks/01_pull_and_filter_institutions.ipynb` end to end (per user preference, do this in
   a Jupyter notebook/kernel rather than a bare script). It:
   - Pulls all institutions from the Scorecard API.
   - Keeps only rows whose `school.accreditor` text matches an accreditor in
     `reference/chea_usde_institutional_accreditors.csv` (dual ED+CHEA recognition).
   - Drops `ownership == 3` (private for-profit); keeps public (1) and private non-profit (2).
   - Drops any row with a non-null `religious_affiliation`.
   - Drops dedicated art/music schools: out of scope since the focus is biomedical science (see
     "Filter 4" below).
   - Drops institutions caught by the tightened religious check (see "Filter 5" below) that the
     `religious_affiliation` field alone missed.
   - Drops rows with no homepage URL.
   - Prints a funnel (count remaining after each filter) so the effect of any one filter is visible
     without re-running the whole pull.
   - Computes `pct_biomedical` (health + biological program share) and sorts by it, descending —
     see "Prioritize by biomedical relevance" below. This is a sort key, not a filter; it never
     removes a row.
   - Adds a `base_domain` column (homepage URL's host, minus scheme/`www.`/path) for de-duplication.
   - Writes the result to `output/accredited_nonprofit_secular_institutions.xlsx` with columns:
     `unitid, institution_name, homepage_url, city, state, accreditor, pct_biomedical,
     has_biomedical_program_data, base_domain, resource_list_url, resource_list_notes` (the last
     two start empty, filled in Step 5), sorted by `pct_biomedical` descending.
3. Sanity-check the output: row count should be roughly in the low thousands (there are ~1,600
   public and several thousand private non-profit Title IV institutions in the U.S.; religious and
   dual-accreditation filtering will cut this down further). If the count looks off by an order of
   magnitude, inspect `df[~df["dual_accredited"]]["accreditor_raw"].unique()` for accreditor-name
   variants missing from the reference CSV before re-running.

### Filter 4: exclude dedicated art/music schools

Scope is biomedical science, so art/music schools are dropped rather than left for manual cleanup —
this is how "Art Academy of Cincinnati" and "American Academy of Dramatic Arts-New York" ended up in
the 1000-institution test run. Two signals, either sufficient to exclude, computed into an
`is_arts_or_music_school` column before the main filter:

- `academics.program_percentage.visual_performing` (Scorecard field, CIP 50 "Visual and Performing
  Arts" — covers fine art, design, film, theater, *and* music in one field) >= 0.5.
- Institution name matches a narrow set of unambiguous multi-word phrases ("art institute", "art
  academy", "school of music", "conservatory of music", "school of design", etc.) — deliberately
  avoids bare "art"/"arts" so it doesn't false-positive on things like "College of Arts and
  Sciences". Needed because many small conservatories/art schools don't report program-mix data at
  all (null percentage, not a low one). Verified against both test runs: 0 false positives, and
  catches 8 real arts/music schools in the 1000-institution sample that the percentage field alone
  would have missed (e.g. Cleveland Institute of Art, Fashion Institute of Technology).

### Filter 5: tighten the religious-institution exclusion

`religious_affiliation` is self-reported to IPEDS and is often blank even for genuinely religious
schools — Asbury University (an evangelical Christian university) passed Filter 3 in the
1000-institution test run despite this (verified: its `accreditor_raw` is just SACSCOC, no
faith-related accreditor). Two additional signals, either sufficient to exclude, computed into an
`is_religious_institution` column before the main filter:

- `accreditor_raw` mentions a national faith-related accrediting organization — see
  `reference/national_faith_related_accreditors.csv` (ABHE, AARTS, AIJS, ATS, TRACS; sourced from
  the same CHEA May 2021 chart as the institutional-accreditor list). These run *alongside* a
  school's regional accreditor, so a religious school can pass Filter 1 via its regional
  accreditation while also carrying one of these.
- `academics.program_percentage.theology_religious_vocation` (CIP 39) >= 0.5 — catches seminaries
  and divinity schools directly.

This still won't catch every religious institution (Asbury has neither signal — it's a
comprehensive university that happens to be evangelical, not flagged by accreditor or program mix).
A stricter pass — institution-name-pattern matching plus a curated manual override list — is
available as a separate, independently-runnable skill that operates on this notebook's *output*
rather than being baked into this pipeline: see
`../institution-resource-list-cleanup/SKILL.md`.

### Prioritize (not filter) by biomedical relevance

Health Professions (CIP 51, `pct_health`) + Biological/Biomedical Sciences (CIP 26,
`pct_biological`) program share, summed into `pct_biomedical`, is used only to **sort** the export
— every institution that passes Filters 1-5 stays in the list regardless of this value. It cannot
be a hard filter: these fields are computed from undergraduate completions only, so standalone
graduate/professional schools (verified: Albert Einstein College of Medicine, A T Still University
of Health Sciences) are null despite being obviously biomedical, while a comprehensive university
with undergrad nursing/health programs (verified: Adelphi, 27.8% health + 10.9% biological) reports
normally. A threshold filter would have wrongly dropped exactly the medical/health-professional
schools most worth keeping. `has_biomedical_program_data` flags the null case so it reads as
"no undergrad program data" rather than silently looking like "0% relevant" in the spreadsheet.

Sorting instead of filtering means Step 5 (the slow, per-domain, agentic part) should work through
the export in the order it's already in — highest biomedical relevance first — rather than
alphabetically, so time spent searching goes to the most relevant institutions first if the full
list can't be finished in one sitting.

### De-duplicate by `base_domain` before Step 5

Multiple institution rows often share a homepage domain — branch/satellite campuses or
multi-location systems served by one shared library site. Confirmed in the 40-institution test run:
Ameritas College and its South Bay Correctional Facility campus (`ameritas.edu` vs `www.ameritas.edu`
— `base_domain` normalizes both), and Albizu University's Miami and San Juan campuses (both
`www.albizu.edu`), each turned out to have the identical resource page. Searching per-row for these
would repeat identical work. The notebook's dedup-summary cell reports how many unique domains exist
vs. total rows — **Step 5 should search once per unique `base_domain`**, not once per row.

### Step 5: find each domain's resources-list page (agentic, once per domain)

This step cannot be scripted purely — it requires judgment about which page on each institution's
site is genuinely "the resources list" — so do it domain by domain using `WebSearch` (and `WebFetch`
to confirm a candidate page), then persist the result immediately with
`scripts/update_resource_entry.py` so progress survives interruption. Do not hold hundreds of
results in memory to write out at the end. (The commands below assume the working directory is this
skill's own top-level folder, `accredited-institution-resources/`, not `scripts/` itself.)

For each unique `base_domain`:

1. Search for the library's resources/databases page or a biomedical/health-sciences subject guide,
   e.g.:
   - `WebSearch("<institution name> library databases A-Z")`
   - `WebSearch("<institution name> library research guides biomedical" )`
   - `WebSearch("site:<homepage domain> libguides biomedical OR health sciences")`
   - LibGuides-based library sites are common — a URL containing `libguides.` or
     `guides.library.` is a strong signal.
2. Prefer, in order: (a) a subject/discipline guide specifically for biomedical or health sciences,
   (b) a general "databases A-Z" or "electronic resources" list from the library, (c) the library's
   homepage if no more specific list page exists.
3. `WebFetch` the candidate URL to confirm it's actually a resources listing (not a login wall, a
   404, or an unrelated page) before recording it.
4. Record the result immediately (right after that domain is resolved — see "Resuming after an
   interruption" below for why this matters), applying it to every row sharing that domain in one
   call:
   ```
   python scripts/update_resource_entry.py --xlsx ../output/accredited_nonprofit_secular_institutions.xlsx \
     --domain <base_domain> --url "<found url>" --notes "<one-line note, e.g. how it was found, or why nothing was found>"
   ```
   Use `--unitid <unitid>` instead of `--domain` for a one-off correction to a single row (e.g. a
   branch campus that turns out to have its own distinct library page despite sharing a domain).
   If nothing suitable is found after a reasonable search effort, leave `--url` empty and record
   why in `--notes` (e.g. "no public library site found") rather than skipping the domain silently.
5. Batch this work — use `TaskCreate`/`TaskUpdate` to track progress across the full domain list (it
   will be too long to finish in one turn), and process domains in small chunks (e.g. 5-10 at a
   time) in the spreadsheet's existing order (highest biomedical relevance first) rather than
   attempting the entire spreadsheet at once or re-sorting it alphabetically.

### Resuming after an interruption (usage-limit cooldowns, context limits, or picking work back up later)

The full domain list is too long to finish in one session, and a Claude usage limit can force a
cooldown mid-run — so the workflow is built to never lose finished work and to resume cheaply:

- **The xlsx is the only source of truth for what's done.** `update_resource_entry.py` writes to
  disk immediately, so anything already recorded survives a cooldown, a context-limit compaction,
  or a closed session without any special handling.
- **The only thing actually at risk is a domain that's been searched but not yet recorded** — e.g.
  a cooldown hits between deciding on a URL and running `update_resource_entry.py`. Keep this
  window small: call `update_resource_entry.py` for each domain as soon as it's resolved (or after
  a small batch of 5-10), not after searching a large batch and writing them all at the end. Don't
  hold dozens of found-but-unwritten results in context.
- **Run `scripts/step5_status.py --xlsx ../output/accredited_nonprofit_secular_institutions.xlsx`
  at the start of every Step 5 session** (fresh or resumed) to list exactly which base_domains
  still need a search, instead of re-scanning the whole spreadsheet or guessing where a prior
  session left off. It also writes `output/step5_checkpoint.json` — a small, gitignored,
  regenerable snapshot (domains done/remaining, timestamp) that's cheap to re-read on resume; it's
  derived from the xlsx, never authoritative on its own, so it can't drift out of sync with it.
- **If a usage-limit warning appears (or you're ending a turn with domains still remaining):**
  finish and record the domain currently in progress (or abandon it cleanly — don't leave a
  half-decided result unwritten), run `step5_status.py` to refresh the checkpoint, update the
  relevant `TaskUpdate`/`TaskList` entries with what's left, and stop. Don't start a new domain you
  won't be able to finish and record before the cooldown hits. A cooldown is a hard usage-limit
  pause enforced by the harness/subscription, not a fixed timer, so don't try to schedule an
  automatic resume — the next session (yours or the user's) just runs `step5_status.py` and
  continues from its output.

## Keeping the reference lists current

Both `reference/chea_usde_institutional_accreditors.csv` and
`reference/national_faith_related_accreditors.csv` reflect CHEA's May 2021 published chart. To
refresh either:

1. Fetch the current chart (check https://www.chea.org/chea-and-usde-recognized-accrediting-organizations
   for a newer PDF link; use a browser `User-Agent` header since chea.org 403s generic bots).
2. Render the relevant PDF page(s) to an image and read the bullet/dash columns directly — the
   PDF's extracted text mangles the bullet (recognized) and dash (not recognized) glyphs into
   identical characters, so text extraction alone cannot distinguish them. The faith-related
   accreditors are in the "NATIONAL FAITH-RELATED ACCREDITING ORGANIZATIONS" section of Part I,
   in a two-column layout that also gets jumbled in plain-text extraction — render to an image for
   this section too.
3. Update the relevant CSV and re-run Step 1-4 filtering.
