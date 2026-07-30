"""Update resource_list_url / resource_list_notes in the output spreadsheet for one institution
(--unitid) or every institution sharing a homepage domain (--domain).

Used during Step 5 so progress is saved after every search instead of held in memory for the whole
run. Safe to call repeatedly. Many rows share a `base_domain` (branch/satellite campuses, or
multi-location systems served by one library site) — use --domain to record one search result for
all of them at once instead of repeating the same search per institution.

Usage (run from the accredited-institution-resources/ directory):
    python scripts/update_resource_entry.py --xlsx ../output/accredited_nonprofit_secular_institutions.xlsx \
        --unitid 12345 --url "https://library.example.edu/az-databases" --notes "found via subject guide search"

    python scripts/update_resource_entry.py --xlsx ../output/accredited_nonprofit_secular_institutions.xlsx \
        --domain example.edu --url "https://library.example.edu/az-databases" --notes "shared by all example.edu campuses"
"""
import argparse
import pandas as pd


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--xlsx", required=True)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--unitid", type=int, help="update a single institution by unitid")
    target.add_argument("--domain", help="update every row sharing this base_domain")
    parser.add_argument("--url", default="")
    parser.add_argument("--notes", default="")
    args = parser.parse_args()

    df = pd.read_excel(args.xlsx)

    if args.unitid is not None:
        mask = df["unitid"] == args.unitid
        if not mask.any():
            raise SystemExit(f"unitid {args.unitid} not found in {args.xlsx}")
    else:
        mask = df["base_domain"] == args.domain
        if not mask.any():
            raise SystemExit(f"base_domain {args.domain!r} not found in {args.xlsx}")

    # Empty resource_list_url/notes columns round-trip through xlsx as all-NaN (float64), so
    # cast to object before assigning strings into them.
    df["resource_list_url"] = df["resource_list_url"].astype(object)
    df["resource_list_notes"] = df["resource_list_notes"].astype(object)
    df.loc[mask, "resource_list_url"] = args.url
    df.loc[mask, "resource_list_notes"] = args.notes
    df.to_excel(args.xlsx, index=False)
    print(f"Updated {mask.sum()} row(s)")


if __name__ == "__main__":
    main()
