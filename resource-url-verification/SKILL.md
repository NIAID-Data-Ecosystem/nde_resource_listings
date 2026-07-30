---
name: resource-url-verification
description: Check every resource_list_url in a spreadsheet (e.g. the output of institution-resource-list-cleanup) for real HTTP 200 status and for "soft 404s" — pages that return 200 but whose title/heading text says the content isn't actually there. Adds the results as new columns in a new output file, never overwriting the input. Use when asked to test, verify, health-check, or validate the library/resource URLs in one of these spreadsheets.
---

# Resource URL verification

Checks every URL in a spreadsheet's `resource_list_url` column and records whether it's actually
reachable, not just whether it was found by search. This is a separate, independently runnable
skill: it makes no assumptions about how the spreadsheet was produced, only that it has a
`resource_list_url` column — the typical input is
`output/accredited_nonprofit_secular_institutions_unique_resource_urls.xlsx` (one row per unique
URL, produced by `institution-resource-list-cleanup`), since that avoids re-checking the same URL
once per institution.

**Writes a new output file. Never overwrites its input.**

## What "broken" means here

Two distinct failure modes, both worth catching:

1. **Not HTTP 200.** The request itself fails, times out, or returns a non-2xx status (404, 403,
   500, a redirect loop, a DNS/connection failure, an SSL error, etc.) — recorded as-is in
   `http_status` (an int for a real response, or an exception-type string like `Timeout` /
   `ConnectionError` / `SSLError` for a failed request).
2. **Soft 404s.** The request *does* return 200, but the page itself is a "not found" / "bad
   request" / generic error page — common on library sites where a removed LibGuides page, an
   expired proxy link, or a decommissioned subdomain redirects to a generic campus error page that
   the web server still serves with a 200. A plain status-code check can't catch this; the page's
   *content* has to be inspected.

## How soft-404 detection works

Fetches each page (capped to the first ~40KB — plenty for `<title>` and heading tags, which is
where this kind of message is almost always rendered as prominent, large text, not buried in body
copy) and only proceeds if the response's `Content-Type` is HTML (a PDF, image, or other binary
resource can't be a "soft 404 page" in this sense, so those are left alone). Extracts the `<title>`
and any `<h1>`/`<h2>`/`<h3>` heading text, strips inner tags, and checks that combined text — not
the full page body — against `SOFT_404_PATTERNS` in the notebook: a regex covering both explicit
error codes (`404`, `400`, `410`, "error 404", etc.) and common natural-language phrasing ("page not
found", "we can't find that page", "no longer exists", "broken link", etc.).

Restricting the check to title/heading text (rather than the whole page) is deliberate: it targets
exactly the "large text told the user it's missing" signal the check is meant to catch, and avoids
false positives from unrelated body text that happens to mention an unrelated 404 somewhere on a
real, working page (e.g. a page listing "common HTTP errors" as documentation).

This is a heuristic, not a certainty — flag results for human review rather than treating
`is_soft_404 = True` as an automatic "remove this row." A page whose title genuinely contains one of
these phrases for an unrelated reason would still be flagged; conversely, a soft-404 page using
unusual wording (no keyword match) won't be caught. See `soft_404_match_text` in the output for the
exact matched snippet, to make a manual check fast.

## Running it

`notebooks/01_verify_resource_urls.ipynb` has two sections:

**First pass** (fast, high concurrency):

1. Reads `INPUT_PATH` (default: `output/accredited_nonprofit_secular_institutions_unique_resource_urls.xlsx`).
2. Checks every row's `resource_list_url` concurrently (`MAX_WORKERS` threads, default 15 — these
   are ~1,800 different hosts, not repeated hits to one site, so moderate concurrency is safe) with
   a browser `User-Agent` header (many library/campus sites 403 the default `requests` UA — the
   same gotcha `accredited-institution-resources` ran into during its own web searches) and a
   15s timeout per request.
3. Adds six columns to every row: `http_status`, `final_url` (after redirects), `is_soft_404`,
   `soft_404_match_text`, `page_title`, `checked_at` (UTC timestamp of the check).
4. Writes `output/unique_resources_checked.xlsx`.
5. Prints a summary funnel: OK / non-200 / soft-404-suspected / request-failed counts.

**Second pass — recheck non-200 rows at lower concurrency:** some non-200 results from the fast
first pass are genuinely broken links, but some (particularly 429s, and some `ConnectionError`s) are
just an anti-bot/rate-limit defense reacting to many near-simultaneous requests, not a real dead
link. This section re-requests only the rows that weren't a clean 200 above, at much lower
concurrency (`RECHECK_MAX_WORKERS`, default 6) with a retry policy that specifically backs off on
429s (`respect_retry_after_header`, honoring the server's `Retry-After` if it sends one). It adds
`was_rechecked` and `http_status_before_recheck` so it's visible exactly which rows were touched and
what changed, then writes `output/unique_resources_double_checked.xlsx`.

Both output filenames are fixed (not derived from the input filename or timestamped) — re-running
either section later (e.g. to check for link rot after months) simply refreshes that same file with
current results, which is the intended behavior here: unlike the frozen upstream deliverables this
skill reads from, "the current state of these links" is exactly what's meant to be kept up to date
in place. (Contrast with `nde-backlink-check`, which deliberately *does* write a fresh dated file
each time it's run, since that skill is meant to support comparing link health over time.)

## Notes on scope and limits

- A GET (not HEAD) is used throughout, since the soft-404 check needs the actual body — some sites
  respond differently or reject HEAD entirely.
- SSL certificate validation is never disabled. An `SSLError` is recorded as a failure rather than
  silently retried without verification, since disabling cert validation would be a real security
  downgrade for what's ultimately arbitrary external content.
- Transient 502/503/504 responses get a couple of automatic retries with backoff (via a
  `urllib3.Retry` adapter) before being recorded as a failure — a single flaky response shouldn't
  need a full separate re-run of the notebook to resolve.
- This only checks reachability and template-level "not found" text. It does not verify that the
  page is *actually* the right subject-specific database list (that judgment call already happened
  during Step 5 in `accredited-institution-resources`) — only that the URL still resolves to real
  content at all.
