---
name: institution-resource-list-cleanup
description: Post-process the spreadsheet produced by the accredited-institution-resources skill — tighten the religious-institution and arts-school exclusions beyond what that pipeline catches, and de-duplicate rows down to one per unique library/resource URL. Runs entirely on an existing xlsx (no API access needed) and always writes a new file, never overwriting the input. Use when asked to clean up, tighten filtering on, or de-duplicate an already-generated institution/resource-list spreadsheet.
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

## Operation 1: tighten the religious-institution and arts-school filters

`accredited-institution-resources`'s Filter 5 (religious) only catches institutions via two
signals: a faith-related accreditor name, or a >=50% undergraduate theology-program share. Filter 4
(arts/music) only catches institutions via a >=50% visual/performing-arts program share, or a
narrow name pattern. Several institutions were found, during full Step 5 runs, to slip through both
Filter 5's signals (seminaries, yeshivas, and other clearly-religious schools whose Scorecard data
alone doesn't flag them) and Filter 4's (dedicated art/design schools whose Scorecard data alone
doesn't flag them either).

This operation adds two more signals per category, computed independently of anything in the
upstream skill:

**Religious:**
- **`RELIGIOUS_NAME_PATTERN`** (in the notebook) — a regex over `institution_name` for unambiguous
  religious-institution phrases: `seminary`, `yeshiva`, `talmudic`, `rabbinical`, `torah`,
  `jewish institute of religion`, `bible institute`, `bible college`, `theological seminary`,
  `divinity school`, etc. Verified against every institution it matches: each one's `accreditor`
  field is a plain regional accreditor with no faith-related accreditor and a low/null
  theology-program share, i.e. neither of the upstream skill's two signals would have caught it.
- **`reference/manual_religious_institution_overrides.csv`** (unitid + institution_name + reason)
  — a small, hand-curated list for institutions that are religious but have *no* matching keyword
  in their name at all (Regent University, Calvin University, Spertus College, Columbia
  International University, Hebrew College, Thomas Aquinas College - New England).

**Arts/design:**
- **`ARTS_NAME_PATTERN`** (in the notebook) — a regex over `institution_name` for exact phrases:
  `college of the arts`, `college of fine arts`, bare `conservatory`, `visual arts`. Deliberately
  exact phrases rather than a general `college of arts?\b` pattern — that broader version was tried
  first and rejected because it matched "Paul Smiths College of Arts and Science," a comprehensive
  college that isn't an art school at all. Always check a candidate pattern against the full
  institution list before adding it, the same way.
- **`reference/manual_arts_institution_overrides.csv`** (unitid + institution_name + reason) — for
  dedicated art/design schools with no matching keyword at all (Pratt Institute — just a surname +
  "Institute," College for Creative Studies — generic-sounding name, Cooper Union — "Art" only
  appears inside a specific historical phrase, "...for the Advancement of Science and Art," too
  fragile to generalize into a pattern).

Both override lists are deliberately kept as explicit lists rather than ever-widening either regex
to catch these by name — a pattern broad enough to match "Regent," "Calvin," or "Pratt" would
false-positive on secular/non-arts institutions with similar-sounding names. Add to a list only when
a specific institution is confirmed religious/arts-focused by other means (there's no bulk source to
refresh either from); neither is sourced from CHEA and neither has anything to do with the
accreditor reference lists in the other skill.

Run `notebooks/01_filter_and_dedupe.ipynb`'s first section against an input xlsx: it reports which
rows match which signal (broken out by religious vs. arts, name-pattern vs. override), removes them,
and writes `<input_stem>_filtered.xlsx` alongside the input (never overwriting it).

If more coverage is needed later than the regexes + manual lists give, the next step up for
religious institutions is cross-referencing against a curated external membership list (Council for
Christian Colleges & Universities, Association of Catholic Colleges and Universities) rather than
continuing to grow either regex or either override list by hand indefinitely. No equivalent
membership-list source is known for arts schools; keep extending the manual override list as new
gaps are found.

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
