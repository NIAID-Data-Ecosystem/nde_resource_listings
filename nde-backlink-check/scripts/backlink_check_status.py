"""Report NDE backlink-check progress and write a resumable checkpoint file.

The working xlsx is the single source of truth for progress (a row counts as "checked" once
backlink_check_notes is non-empty, whether it was actually searched or skipped as ineligible) --
this script doesn't track any separate state, it just summarizes the xlsx so nothing can drift out
of sync with it. Run it:

  - At the start of every check_nde_backlinks.py session, fresh or resumed after an interruption, to
    see how much work remains before deciding on a --limit for this run.
  - Any time, to see how many resources have an NDE backlink found so far, without doing any
    network activity.

Usage (run from the nde-backlink-check/ directory):
    python scripts/backlink_check_status.py --xlsx ../output/2026-07-30_unique_resources_backlink_check.xlsx
"""
import argparse
import json
import pathlib
from datetime import date, datetime, timezone

import pandas as pd

from check_nde_backlinks import DEFAULT_SOURCE_XLSX, compute_eligible_mask


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--xlsx", default=None,
        help="Working xlsx to report on. Defaults to today's dated file "
             "('<today>_unique_resources_backlink_check.xlsx') next to the default --source, matching "
             "check_nde_backlinks.py's own default -- pass an explicit path to check a different date.",
    )
    parser.add_argument(
        "--checkpoint", default=None,
        help="path to write the checkpoint JSON (default: <xlsx's dir>/nde_backlink_checkpoint.json)",
    )
    args = parser.parse_args()

    if args.xlsx:
        xlsx_path = pathlib.Path(args.xlsx)
    else:
        default_dir = pathlib.Path(DEFAULT_SOURCE_XLSX).parent
        xlsx_path = default_dir / f"{date.today().isoformat()}_unique_resources_backlink_check.xlsx"

    if not xlsx_path.exists():
        print(f"{xlsx_path} doesn't exist yet -- run check_nde_backlinks.py first to create it.")
        return

    df = pd.read_excel(xlsx_path)

    eligible_mask = compute_eligible_mask(df)
    notes_present = df["backlink_check_notes"].notna() & (df["backlink_check_notes"].astype(str).str.strip() != "")
    checked_mask = eligible_mask & notes_present

    total_eligible = int(eligible_mask.sum())
    n_checked = int(checked_mask.sum())
    n_remaining = total_eligible - n_checked
    n_found = int((df["has_nde_backlink"] == True).sum())  # noqa: E712
    n_not_found = int(((df["has_nde_backlink"] == False) & checked_mask).sum())  # noqa: E712

    print(f"{n_checked}/{total_eligible} eligible rows checked, {n_remaining} remaining")
    print(f"  {n_found} found with an NDE backlink so far")
    print(f"  {n_not_found} checked, no backlink found")

    if n_remaining:
        remaining = df.loc[eligible_mask & ~notes_present, ["unitid", "institution_name", "resource_list_url"]]
        print()
        print("Next up (first 20 of remaining):")
        for _, row in remaining.head(20).iterrows():
            print(f"  {row['unitid']} | {row['institution_name']} | {row['resource_list_url']}")

    checkpoint_path = (
        pathlib.Path(args.checkpoint) if args.checkpoint else xlsx_path.parent / "nde_backlink_checkpoint.json"
    )
    checkpoint = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "xlsx": str(xlsx_path),
        "total_eligible": total_eligible,
        "n_checked": n_checked,
        "n_remaining": n_remaining,
        "n_found": n_found,
        "n_not_found": n_not_found,
    }
    checkpoint_path.write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")
    print(f"\nCheckpoint written to {checkpoint_path}")


if __name__ == "__main__":
    main()
