---
name: nde-backlink-check
description: For every resource_list_url in a spreadsheet, search the resource's site for a link/mention of the NIAID Data Ecosystem (https://data.niaid.nih.gov) and record whether one was found in a new has_nde_backlink column. Runs independently of the URL-verification skills (does its own reachability check if they haven't run) and writes a dated output file each time, so re-running later to compare backlink coverage over time never overwrites an older run. Long-running and resumable — checkpoints after every small batch. Use when asked to check, search for, or verify NDE backlinks across the institution resource spreadsheet.
---

# NDE backlink check

For institution resources (library A-Z pages, subject guides, etc.), this searches each resource's
site for a reference to the NIAID Data Ecosystem
([https://data.niaid.nih.gov](https://data.niaid.nih.gov)) and records whether one was found.

It's typically the last stage in the chain: `accredited-institution-resources` →
`institution-resource-list-cleanup` → `resource-url-verification` → **`nde-backlink-check`** — but
unlike the other three, it doesn't require the earlier ones to have run. See "Independent operation"
below.

## Independent operation

The only column this actually requires is `resource_list_url`. If the input also has `http_status`
and `is_soft_404` (i.e. it's chained from `resource-url-verification`'s output, the normal case),
rows already known to be broken are skipped immediately with no network request — no point
re-checking a link that's already confirmed dead. If those columns *aren't* present — e.g. pointed
directly at `institution-resource-list-cleanup`'s raw de-duplicated output, or any other spreadsheet
with just a URL column — every row with a URL is treated as eligible, and this skill's own fetch
(step 1 of "How the search works" below) is what determines reachability instead.

## Why this is resumable and dated, unlike the other skills in this tree

`institution-resource-list-cleanup` and `resource-url-verification` each finish in a few minutes and
write a fixed-name output file that's simply refreshed on every re-run — appropriate for something
fast enough to just redo in full, where only the *current* state matters.

This skill is neither of those things:

- **Slow enough to need resumability.** Checking a resource for an NDE reference isn't always a
  single request — see "How the search works" — and across 1,000+ eligible resources that's enough
  requests that a run can take a while and may need to be interrupted (a timeout, a network blip, a
  deliberate pause) partway through. So it follows the same resumable design
  `accredited-institution-resources` uses for its own slow, per-domain Step 5 search:
  - **The working xlsx is the only source of truth for progress.** `scripts/check_nde_backlinks.py`
    reads whatever state is already in the file and only processes rows that haven't been checked
    yet (a row counts as checked once `backlink_check_notes` is non-empty — true even for rows
    skipped as ineligible, so those are never redundantly reprocessed).
  - **Results are flushed to disk every 10 completions** (not held in memory for the whole run), so
    an interruption loses at most a small in-flight batch, never the rows already finished.
  - Run `scripts/backlink_check_status.py` any time to see progress (checked / remaining / found so
    far) without doing any network activity.
- **Meant to be compared over time, not just refreshed.** Whether a site links to NDE can change
  month to month as libraries update their catalogs, so unlike the other skills here, re-running
  this one later shouldn't silently overwrite the previous run's snapshot — you'd lose the ability to
  see how backlink coverage changed. So the output file is named by date (see "Output filename"
  below) rather than fixed.

These two properties interact in one way worth being explicit about: **the working file this skill
writes to *is* updated in place across runs (unlike the other three skills' "always a fresh file"
rule) — but only within the same dated file.** Resuming an interrupted run and starting a genuinely
new dated check are the same command by default; see below.

## Output filename

Defaults to `<today's date>_unique_resources_backlink_check.xlsx` (e.g.
`2026-07-30_unique_resources_backlink_check.xlsx`), written next to `--source`.

- Run the command again **the same day** → same default path → resumes that day's file exactly
  where it left off (today's date hasn't changed, so nothing special is needed).
- Run it again **on a later day** with no `--xlsx` given → a **new** file for that new date, so a
  deliberate re-check (e.g. "has backlink coverage changed since last quarter?") never overwrites the
  earlier snapshot.
- To resume a specific still-in-progress file from a previous day instead of starting a new one for
  today, pass that exact path explicitly via `--xlsx`.

## How the search works

For each eligible `resource_list_url`:

1. Fetch the page. If the response, after following redirects, lands on `data.niaid.nih.gov`
   directly, that's an immediate match.
2. Otherwise, search the fetched page's raw HTML (up to `MAX_BODY_BYTES`, currently 1MB — generous,
   since some library A-Z pages listing hundreds of databases can be large, but still bounded) for
   the literal substring `data.niaid.nih.gov`, case-insensitively. A plain substring search (not
   strict `<a href>` parsing) deliberately also catches a URL mentioned as visible text, not just a
   proper hyperlink, and doesn't care whether it's wrapped in an EZproxy prefix or similar.
3. If not found directly, **most library "A-Z database" pages don't link straight to the external
   database — they link to an internal LibGuides/CMS "asset" page that then forwards to the real
   external site** (common with Springshare LibGuides). So this extracts every same-domain anchor
   link on the page whose *visible link text* mentions NIAID, "NDE", or "data ecosystem"
   (`CANDIDATE_TEXT_PATTERN`), and follows up to `MAX_CANDIDATE_LINKS` (5) of those, checking each
   the same way (direct-domain-match or substring match).
4. If nothing is found after that, the resource is recorded as `has_nde_backlink = False`, with a
   note on how many candidate pages (if any) were checked.

This is a bounded heuristic, not a full site crawl — deliberately, since crawling every single
outbound link on every A-Z page (some list 100+ databases) across 1,000+ resources would be enormous
and mostly wasted effort. The trade-off: an NDE reference that exists on the site but isn't reachable
via a same-domain link whose *visible text* mentions NIAID/NDE/"data ecosystem" — e.g. it's linked
under an unrelated generic label, or requires navigating more than one hop deep — will be recorded as
not found. `backlink_check_notes` always says exactly what was checked, so a false negative here is
easy to spot-check and correct by hand later if it matters.

## Output columns

- `has_nde_backlink` — `True` / `False` once checked; blank for rows not yet reached.
- `nde_backlink_source_url` — the exact page where the reference was found (the resource page
  itself, or a candidate page reached from it); blank if not found.
- `backlink_check_notes` — what happened: found directly, found via a candidate page (and which
  one), not found after checking N candidates, skipped as ineligible (no URL, or a source link
  already known invalid), or a fetch error. Non-empty here is what marks a row as "already
  processed" for resumability.
- `backlink_checked_at` — UTC timestamp of the check.

## Running it

```bash
python scripts/check_nde_backlinks.py
```

- `--xlsx` — the working file. Defaults to today's dated filename next to `--source` (see "Output
  filename" above); created automatically if it doesn't exist yet. Pass an explicit path to resume a
  specific earlier dated file instead.
- `--source` — only used the first time a given `--xlsx` is created, to initialize it (default:
  `resource-url-verification`'s output, `output/unique_resources_double_checked.xlsx`). Point this
  at a different spreadsheet — e.g. `institution-resource-list-cleanup`'s raw
  `output/accredited_nonprofit_secular_institutions_unique_resource_urls.xlsx` — to run without
  either URL-verification skill having been run first (see "Independent operation" above).
- `--limit N` — process at most N rows this invocation (useful for testing, or for deliberately
  working in bounded batches across a slow connection or a usage-limit cooldown).
- `--workers N` — concurrency (default 8; these are ~1,000+ different hosts plus a handful of
  same-domain candidate pages each, so moderate concurrency is safe — see
  `resource-url-verification`'s SKILL.md for the same reasoning applied there).

Check progress at any time, from the same directory (same `--xlsx`/`--source` defaults apply):

```bash
python scripts/backlink_check_status.py
```
