"""Report Step 5 progress and write a resumable checkpoint file.

The output spreadsheet is the single source of truth for progress (a row is "done" once
resource_list_url is filled in) — this script doesn't track any separate state, it just summarizes
the xlsx so nothing can drift out of sync with it. Run it:

  - At the start of every Step 5 session, fresh or resumed after an interruption (a Claude usage-limit
    cooldown, a context-limit compaction, or simply picking the work back up later), to see exactly
    which base_domains still need a resource_list_url instead of re-scanning the whole spreadsheet
    by hand or accidentally redoing finished work.
  - Periodically during a long Step 5 run (e.g. after every batch of update_resource_entry.py calls)
    to refresh output/step5_checkpoint.json, and again right before deliberately stopping (a usage
    limit warning appears, or the turn is ending) so the checkpoint always reflects the latest writes.

Remaining domains are listed in the xlsx's existing row order (highest biomedical relevance first),
not alphabetically, so this doubles as a priority-ordered worklist.

Usage (run from the accredited-institution-resources/ directory):
    python scripts/step5_status.py --xlsx ../output/accredited_nonprofit_secular_institutions.xlsx
"""
import argparse
import json
import pathlib
from datetime import datetime, timezone

import pandas as pd


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--xlsx", required=True)
    parser.add_argument(
        "--checkpoint",
        default=None,
        help="path to write the checkpoint JSON (default: <xlsx's dir>/step5_checkpoint.json)",
    )
    args = parser.parse_args()

    xlsx_path = pathlib.Path(args.xlsx)
    df = pd.read_excel(xlsx_path)

    done_mask = df["resource_list_url"].notna() & (df["resource_list_url"].astype(str).str.strip() != "")
    done_domains = sorted(df.loc[done_mask, "base_domain"].unique().tolist())

    # Preserve the xlsx's existing row order (highest biomedical relevance first, see SKILL.md)
    # rather than re-sorting domains alphabetically, so remaining work is listed in the same
    # priority order Step 5 should actually process it in.
    remaining = df.loc[~done_mask]
    remaining_domains = {
        domain: group[["unitid", "institution_name"]].to_dict("records")
        for domain, group in remaining.groupby("base_domain", sort=False)
    }

    total_domains = df["base_domain"].nunique()
    n_done = len(done_domains)
    n_remaining = len(remaining_domains)

    print(
        f"{n_done}/{total_domains} base domains done, {n_remaining} remaining "
        f"({int(done_mask.sum())}/{len(df)} institution rows filled in)"
    )
    for domain, rows in remaining_domains.items():
        names = ", ".join(r["institution_name"] for r in rows)
        print(f"  - {domain}: {names}")

    checkpoint_path = (
        pathlib.Path(args.checkpoint) if args.checkpoint else xlsx_path.parent / "step5_checkpoint.json"
    )
    checkpoint = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "xlsx": str(xlsx_path),
        "total_domains": total_domains,
        "done_domains": done_domains,
        "remaining_domains": remaining_domains,
    }
    checkpoint_path.write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")
    print(f"\nCheckpoint written to {checkpoint_path}")


if __name__ == "__main__":
    main()
