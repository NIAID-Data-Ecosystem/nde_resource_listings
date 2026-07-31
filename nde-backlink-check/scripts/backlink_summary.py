"""Summarize backlink-check results at the *institution* level, not the row level.

The working xlsx is de-duplicated by resource_list_url (institution-resource-list-cleanup's
Operation 2), so a single row can represent multiple institutions that happen to share a resource
page -- their unitid/institution_name are joined with "; " in that row. Counting rows would
undercount institutions whenever that happened, so this splits those joined fields back out and
counts distinct unitids instead.

Reports two numbers:
  1. How many institutions have a working (HTTP 200, non-soft-404) library/resource URL.
  2. How many institutions' resource page backlinks to the NIAID Data Ecosystem Discovery Portal
     (https://data.niaid.nih.gov).

Usage (run from the nde-backlink-check/ directory):
    python scripts/backlink_summary.py
    python scripts/backlink_summary.py --xlsx ../output/2026-07-31_unique_resources_backlink_check_merged.xlsx
"""
import argparse
import pathlib
from datetime import date

import pandas as pd

from check_nde_backlinks import DEFAULT_SOURCE_XLSX, compute_eligible_mask


def split_unitids(series):
    """Splits "; "-joined unitid strings back into one id per institution."""
    ids = set()
    for value in series.dropna():
        for part in str(value).split(";"):
            part = part.strip()
            if part:
                ids.add(part)
    return ids


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--xlsx", default=None,
        help="Working xlsx to summarize. Defaults to today's dated file next to the default "
             "--source, matching check_nde_backlinks.py's own default -- pass an explicit path "
             "(e.g. a merged file spanning multiple runs) to summarize a different one.",
    )
    args = parser.parse_args()

    if args.xlsx:
        xlsx_path = pathlib.Path(args.xlsx)
    else:
        default_dir = pathlib.Path(DEFAULT_SOURCE_XLSX).parent
        xlsx_path = default_dir / f"{date.today().isoformat()}_unique_resources_backlink_check.xlsx"

    if not xlsx_path.exists():
        print(f"{xlsx_path} doesn't exist -- pass an explicit --xlsx pointing at a backlink-check file.")
        return

    df = pd.read_excel(xlsx_path)

    total_institutions = split_unitids(df["unitid"])

    working_mask = compute_eligible_mask(df)  # has a URL, HTTP 200, not a soft-404
    working_institutions = split_unitids(df.loc[working_mask, "unitid"])

    backlink_mask = df["has_nde_backlink"] == True  # noqa: E712
    backlink_institutions = split_unitids(df.loc[backlink_mask, "unitid"])

    print(f"Source: {xlsx_path}")
    print(f"{len(df)} rows representing {len(total_institutions)} institutions")
    print()
    print(f"{len(working_institutions)}/{len(total_institutions)} institutions have a working "
          f"(HTTP 200, non-soft-404) library/resource URL")
    print(f"{len(backlink_institutions)}/{len(total_institutions)} institutions backlink to the "
          f"NIAID Data Ecosystem Discovery Portal (data.niaid.nih.gov)")


if __name__ == "__main__":
    main()
