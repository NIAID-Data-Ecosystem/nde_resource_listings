"""Search each eligible resource_list_url (and a small, targeted set of same-domain pages linked
from it) for a reference to the NIAID Data Ecosystem (https://data.niaid.nih.gov), recording the
result in has_nde_backlink / nde_backlink_source_url / backlink_check_notes / backlink_checked_at.

Runs independently of resource-url-verification: if the input has http_status/is_soft_404 columns
(the normal case, chaining from that skill's output), rows already known to be broken are skipped
without a network request; if it doesn't (e.g. pointed straight at institution-resource-list-cleanup's
raw de-duplicated output, or any other spreadsheet with just a resource_list_url column), every row
with a URL is treated as eligible and this script does its own fetch to find out.

Resumable by design, following the same pattern as accredited-institution-resources' Step 5: the
*working* xlsx (--xlsx) is the only source of truth for progress. A row counts as "already
processed" once its backlink_check_notes is non-empty -- true even for rows skipped as ineligible,
so those are never redundantly reprocessed. Results are flushed to disk every CHECKPOINT_EVERY
completions (not held in memory for the whole run), so an interruption (Ctrl+C, timeout, crash)
never loses more than a small in-flight batch. Re-running this script against the same --xlsx picks
up exactly where it left off.

Unlike resource-url-verification's fixed output filenames, --xlsx defaults to a *dated* filename --
'<today's date>_unique_resources_backlink_check.xlsx' -- so that deliberately re-running the whole
check at a later date (to see how backlink coverage changed) produces a new file rather than
silently refreshing an old one. Running the command again on the *same* day naturally resumes that
same day's file (today's date hasn't changed); to resume a specific still-in-progress file from a
previous day instead of starting a new one for today, just pass that exact path via --xlsx.

See ../SKILL.md for the full rationale behind the search strategy (why it follows a bounded set of
same-domain "candidate" links rather than crawling the whole site).

Usage (run from the nde-backlink-check/ directory):
    python scripts/check_nde_backlinks.py
    python scripts/check_nde_backlinks.py --limit 200 --workers 8
    python scripts/check_nde_backlinks.py --xlsx ../output/2026-07-30_unique_resources_backlink_check.xlsx
"""
import argparse
import pathlib
import re
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_SOURCE_XLSX = "../output/unique_resources_double_checked.xlsx"

NDE_DOMAIN = "data.niaid.nih.gov"
NDE_URL_PATTERN = re.compile(re.escape(NDE_DOMAIN), re.IGNORECASE)
# Visible link text that suggests "this link is worth following to look for the NDE" -- library A-Z
# pages very often link a database's *name* to an internal asset/proxy page rather than straight to
# the external site (common with Springshare LibGuides), so text matching is how a same-domain
# candidate page gets selected for a second look.
CANDIDATE_TEXT_PATTERN = re.compile(r"niaid|\bnde\b|data ecosystem|data discovery engine", re.IGNORECASE)
ANCHOR_RE = re.compile(r'<a\s[^>]*?href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}
TIMEOUT_SECONDS = 15
MAX_CANDIDATE_LINKS = 5
# Generous vs. resource-url-verification's 40KB cap: that skill only needed <title>/<h1-3>, which
# sit near the top of the document. This needs to find a mention/link anywhere on the page, and
# some library A-Z lists (100+ databases) run well past 40KB of HTML.
MAX_BODY_BYTES = 1_000_000
CHECKPOINT_EVERY = 10


def make_session(max_workers):
    session = requests.Session()
    retry = Retry(
        total=2, connect=1, read=1, status=2, backoff_factor=1,
        status_forcelist=[429, 502, 503, 504], allowed_methods=["GET"],
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=max_workers, pool_connections=max_workers)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def strip_tags(fragment):
    return re.sub(r"\s+", " ", TAG_RE.sub(" ", fragment)).strip()


def base_domain(url):
    netloc = urllib.parse.urlparse(url).netloc.lower().split(":")[0]
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def is_nde_url(url):
    return NDE_DOMAIN in url.lower()


def fetch(session, url):
    """Returns (status_code, html_text_or_empty, final_url). Raises on connection-level failure."""
    resp = session.get(url, headers=HEADERS, timeout=TIMEOUT_SECONDS, allow_redirects=True, stream=True)
    with resp:
        content_type = resp.headers.get("Content-Type", "")
        if "html" not in content_type.lower():
            return resp.status_code, "", resp.url
        chunks, total = [], 0
        for chunk in resp.iter_content(chunk_size=8192):
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total >= MAX_BODY_BYTES:
                break
        body = b"".join(chunks).decode(resp.encoding or "utf-8", errors="replace")
        return resp.status_code, body, resp.url


def find_candidate_links(html, page_url, home_domain):
    candidates = []
    seen = set()
    for href, text in ANCHOR_RE.findall(html):
        visible = strip_tags(text)
        if not CANDIDATE_TEXT_PATTERN.search(visible):
            continue
        absolute = urllib.parse.urljoin(page_url, href)
        if base_domain(absolute) != home_domain or absolute in seen:
            continue
        seen.add(absolute)
        candidates.append(absolute)
        if len(candidates) >= MAX_CANDIDATE_LINKS:
            break
    return candidates


def check_one(session, url):
    """Returns (has_backlink: bool, source_url: str, notes: str)."""
    try:
        status, html, final_url = fetch(session, url)
    except requests.exceptions.RequestException as exc:
        return False, "", f"Source page unreachable during backlink check ({type(exc).__name__})"

    if status != 200:
        return False, "", f"Source page returned HTTP {status} during backlink check"
    if is_nde_url(final_url):
        return True, final_url, "Resource page redirects directly to the NIAID Data Ecosystem"
    if NDE_URL_PATTERN.search(html):
        return True, final_url, "Found directly on the resource page"

    home_domain = base_domain(final_url)
    candidates = find_candidate_links(html, final_url, home_domain)
    for candidate in candidates:
        try:
            c_status, c_html, c_final = fetch(session, candidate)
        except requests.exceptions.RequestException:
            continue
        if c_status != 200:
            continue
        if is_nde_url(c_final):
            return True, c_final, f"Linked page redirects directly to the NIAID Data Ecosystem (via {candidate})"
        if NDE_URL_PATTERN.search(c_html):
            return True, c_final, f"Found on a linked page reached via candidate link text match ({candidate})"

    if candidates:
        return False, "", f"Not found on the resource page or {len(candidates)} candidate linked page(s) checked"
    return False, "", "Not found on the resource page; no NIAID/NDE-referencing links found to follow"


def has_verification_columns(df):
    return "http_status" in df.columns and "is_soft_404" in df.columns


def compute_eligible_mask(df):
    """A row is eligible for a backlink check if it has a URL, and -- only when the columns are
    present -- that URL already passed resource-url-verification. Without those columns (running
    independently of that skill), every row with a URL is eligible; this script's own fetch in
    check_one() is then what determines whether that URL is actually reachable."""
    has_url = df["resource_list_url"].notna() & (df["resource_list_url"].astype(str).str.strip() != "")
    if has_verification_columns(df):
        return has_url & (df["http_status"] == 200) & (df["is_soft_404"] == False)  # noqa: E712
    return has_url


def init_working_file(xlsx_path, source_path):
    df = pd.read_excel(source_path)
    df["has_nde_backlink"] = pd.Series([pd.NA] * len(df), dtype=object)
    df["nde_backlink_source_url"] = ""
    df["backlink_check_notes"] = ""
    df["backlink_checked_at"] = ""

    has_url = df["resource_list_url"].notna() & (df["resource_list_url"].astype(str).str.strip() != "")
    eligible = compute_eligible_mask(df)

    df.loc[~has_url, "backlink_check_notes"] = "Not checked: no resource_list_url provided"
    if has_verification_columns(df):
        df.loc[has_url & ~eligible, "backlink_check_notes"] = (
            "Not checked: source link is not valid (see http_status/is_soft_404)"
        )
        source_note = ""
    else:
        source_note = (
            " (no http_status/is_soft_404 columns found in --source -- treating every row with a "
            "resource_list_url as eligible; this script's own fetch will determine reachability)"
        )

    df.to_excel(xlsx_path, index=False)
    n_eligible = int(eligible.sum())
    print(f"Initialized {xlsx_path} from {source_path} "
          f"({len(df)} rows, {n_eligible} eligible for a backlink check){source_note}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--xlsx", default=None,
        help="Working xlsx to check/update. Defaults to '<today>_unique_resources_backlink_check.xlsx' "
             "next to --source (created there if it doesn't exist yet). Pass an explicit path to resume "
             "a specific earlier dated file instead of starting a new one for today.",
    )
    parser.add_argument("--source", default=DEFAULT_SOURCE_XLSX,
                         help="Source xlsx to initialize --xlsx from, if --xlsx doesn't exist yet.")
    parser.add_argument("--limit", type=int, default=None, help="Process at most this many rows this run.")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    source_path = pathlib.Path(args.source)
    if args.xlsx:
        xlsx_path = pathlib.Path(args.xlsx)
    else:
        xlsx_path = source_path.parent / f"{date.today().isoformat()}_unique_resources_backlink_check.xlsx"

    if not xlsx_path.exists():
        init_working_file(xlsx_path, source_path)

    df = pd.read_excel(xlsx_path)
    for col, default in [("has_nde_backlink", pd.NA), ("nde_backlink_source_url", ""),
                         ("backlink_check_notes", ""), ("backlink_checked_at", "")]:
        if col not in df.columns:
            df[col] = default
        df[col] = df[col].astype(object)  # avoid dtype-mismatch warnings when writing str/bool below

    eligible_mask = compute_eligible_mask(df)
    notes_empty = df["backlink_check_notes"].isna() | (df["backlink_check_notes"].astype(str).str.strip() == "")
    pending_mask = eligible_mask & notes_empty
    pending = df.loc[pending_mask]
    if args.limit is not None:
        pending = pending.head(args.limit)

    total_eligible = int(eligible_mask.sum())
    remaining_overall = int(pending_mask.sum())
    print(f"{total_eligible - remaining_overall}/{total_eligible} eligible rows already checked, "
          f"{len(pending)} to process this run (of {remaining_overall} remaining overall)")

    if pending.empty:
        print("Nothing to do.")
        return

    session = make_session(args.workers)
    checked_since_flush = 0
    start = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(check_one, session, row["resource_list_url"]): idx
                   for idx, row in pending.iterrows()}
        for i, future in enumerate(as_completed(futures), start=1):
            idx = futures[future]
            try:
                has_backlink, source_url, notes = future.result()
            except Exception as exc:
                has_backlink, source_url, notes = False, "", f"Unexpected error: {type(exc).__name__}"

            df.at[idx, "has_nde_backlink"] = has_backlink
            df.at[idx, "nde_backlink_source_url"] = source_url
            df.at[idx, "backlink_check_notes"] = notes
            df.at[idx, "backlink_checked_at"] = datetime.now(timezone.utc).isoformat()
            checked_since_flush += 1

            if checked_since_flush >= CHECKPOINT_EVERY or i == len(pending):
                df.to_excel(xlsx_path, index=False)
                checked_since_flush = 0
                print(f"  {i}/{len(pending)} checked this run ({time.time() - start:.0f}s elapsed) -- saved to {xlsx_path}")

    n_found_total = int((df["has_nde_backlink"] == True).sum())  # noqa: E712
    n_checked_now = total_eligible - int(
        (eligible_mask & (df["backlink_check_notes"].isna() | (df["backlink_check_notes"].astype(str).str.strip() == ""))).sum()
    )
    print()
    print(f"Done for this run: processed {len(pending)} rows.")
    print(f"Overall: {n_checked_now}/{total_eligible} eligible rows checked, "
          f"{n_found_total} found with an NDE backlink so far.")


if __name__ == "__main__":
    main()
