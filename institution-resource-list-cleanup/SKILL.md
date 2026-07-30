---
name: institution-resource-list-cleanup
description: Post-process the spreadsheet produced by the accredited-institution-resources skill — tighten the religious-institution exclusion beyond what that pipeline catches, and de-duplicate rows down to one per unique library/resource URL. Runs entirely on an existing xlsx (no API access needed) and always writes a new file, never overwriting the input. Use when asked to clean up, tighten filtering on, or de-duplicate an already-generated institution/resource-list spreadsheet.
---

# Institution resource-list cleanup

Post-processes the output of the `accredited-institution-resources` skill (or any spreadsheet with
the same 11-column schema — see "Expected input schema" below). This is a separate, independently
runnable skill: it never calls the College Scorecard API, never touches `credentials.json`, and
never re-does the agentic Step 5 web search — it only transforms an existing xlsx that already has
`resource_list_url` filled in.

**Every operation in this skill writes a new output file. It never overwrites its input.** The
input spreadsheet (e.g. `output/accredited_nonprofit_secular_institutions.xlsx`) is the ongoing
basis for this project and must stay untouched by anything run from here.

## Expected input schema

One row per institution, with at least these columns (produced by
`accredited-institution-resources`'s Step 1-4 export + Step 5):

`unitid, institution_name, homepage_url, city, state, accreditor, pct_biomedical,
has_biomedical_program_data, base_domain, resource_list_url, resource_list_notes`

## Operation 1: tighten the religious-institution filter

`accredited-institution-resources`'s Filter 5 only catches religious institutions via two signals:
a faith-related accreditor name, or a >=50% undergraduate theology-program share (see that skill's
SKILL.md for why — briefly, the Scorecard API often only returns an institution's *regional*
accreditor even when it also holds a faith-related one, and the theology-program-share field is
undergraduate-only). Several institutions were found to slip through both signals during a full
Step 5 run: seminaries, yeshivas, and other clearly-religious schools whose Scorecard data alone
doesn't flag them.

This operation adds two more signals, computed independently of anything in the upstream skill:

- **`RELIGIOUS_NAME_PATTERN`** (in the notebook) — a regex over `institution_name` for unambiguous
  religious-institution phrases: `seminary`, `yeshiva`, `talmudic`, `rabbinical`, `torah`,
  `jewish institute of religion`, `bible institute`, `bible college`, `theological seminary`,
  `divinity school`, etc. Verified against every institution it matches: each one's `accreditor`
  field is a plain regional accreditor with no faith-related accreditor and a low/null
  theology-program share, i.e. neither of the upstream skill's two signals would have caught it.
- **`reference/manual_religious_institution_overrides.csv`** (unitid + institution_name + reason)
  — a small, hand-curated list for institutions that are religious but have *no* matching keyword
  in their name at all (Regent University, Calvin University, Spertus College, Columbia
  International University). Deliberately kept as an explicit override list rather than widening
  the regex to catch these by name — a pattern broad enough to match "Regent" or "Calvin" would
  false-positive on secular institutions with similar-sounding names. Add to this file only when a
  specific institution is confirmed religious by other means (there's no bulk source to refresh it
  from); it is not sourced from CHEA and has nothing to do with the accreditor reference lists in
  the other skill.

Run `notebooks/01_filter_and_dedupe.ipynb`'s first section against an input xlsx: it reports which
rows match either signal, removes them, and writes `<input_stem>_religious_filtered.xlsx` alongside
the input (never overwriting it).

If more coverage is needed later than the regex + manual list gives, the next step up is
cross-referencing against a curated external membership list (Council for Christian Colleges &
Universities, Association of Catholic Colleges and Universities) rather than continuing to grow
either the regex or the override list by hand indefinitely.

## Operation 2: de-duplicate by resource URL

Many institutions in the source spreadsheet share the exact same `resource_list_url` — not just
branch campuses of the same system (already grouped by `base_domain` upstream), but also different
`base_domain`s that both fell back to the same shared page (e.g. several different Penn State
branch-campus domains all fall back to the same main Penn State Libraries page; several unrelated
community colleges all point to the same statewide consortium database page). De-duplicating by
`base_domain` alone (as the upstream skill does, for planning Step 5 searches) doesn't collapse
these — de-duplicating by `resource_list_url` does.

The output keeps the same 11 columns, one row per unique `resource_list_url`. When multiple
institutions share a URL, their institution-identifying fields (`unitid`, `institution_name`,
`homepage_url`, `city`, `state`, `accreditor`, `base_domain`) become a `; `-joined list of every
institution using that URL — nothing is silently dropped. `pct_biomedical` takes the max across the
group (preserving the sort/priority behavior from the upstream skill) and
`has_biomedical_program_data` is true if any member institution has it. `resource_list_notes` is
also joined (de-duplicated) in case notes differ across the group.

Run `notebooks/01_filter_and_dedupe.ipynb`'s second section against an input xlsx (by default, the
output of Operation 1, but it can run standalone against any xlsx with a `resource_list_url`
column): it writes `<input_stem>_unique_resource_urls.xlsx` alongside the input.

## Running both together vs. independently

The notebook's two sections are independent — each has its own `INPUT_PATH` variable, so either can
run alone against any xlsx matching the schema above. The typical end-to-end use is Operation 1
followed by Operation 2 (tighten, then de-duplicate), but if a spreadsheet has already been tightened
(e.g. it was hand-edited, or Operation 1 was run previously), just run Operation 2 directly against
it.
