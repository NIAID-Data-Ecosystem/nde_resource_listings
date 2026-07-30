# resource_listings

Builds and maintains a spreadsheet of U.S. institutions (accredited, non-profit, non-religious)
along with each institution's library/biomedical resource-list page, and checks whether that page
is reachable and whether it links back to the NIAID Data Ecosystem (NDE).

## Layout

```
resource_listings/
├── accredited-institution-resources/     \
├── institution-resource-list-cleanup/     \  "skills" -- see below
├── resource-url-verification/             /
├── nde-backlink-check/                   /
├── output/                               deliverables + working files (gitignored except .md)
├── credentials.json                      College Scorecard API key (gitignored, never commit)
└── .gitignore
```

## What a "skill" is here

Each of the four top-level directories (`accredited-institution-resources`,
`institution-resource-list-cleanup`, `resource-url-verification`, `nde-backlink-check`) is a
self-contained **skill**: a distinct stage of the pipeline, each with its own `SKILL.md` documenting
what it does, why, and how to run it, plus its own `notebooks/`, `scripts/`, and/or `reference/`
subdirectories. **Read a skill's `SKILL.md` before touching anything inside it** — that's where the
actual rationale, gotchas, and exact invocation commands live; this file only gives the map.

These directories used to live under `.claude/skills/`, which is Claude Code's convention for
auto-discovered, agent-invokable skills (surfaced via the `Skill` tool). They've been moved to the
top level specifically to reduce nesting and stand alone as plain, readable project structure —
**they are no longer auto-discovered by the `Skill` tool.** Treat each directory as a manually-run
module: open its `SKILL.md`, follow its instructions, run its notebook or scripts directly.

**Working-directory convention:** every skill's documented commands assume you've `cd`'d into that
skill's own top-level directory first (e.g. `cd accredited-institution-resources`), not into its
`notebooks/` or `scripts/` subdirectory. Notebooks are the one exception — Jupyter/nbconvert sets a
notebook's working directory to wherever the `.ipynb` file itself lives, so paths inside a notebook
are already written relative to its own `notebooks/` folder.

## The pipeline, in order

1. **`accredited-institution-resources`** — pulls institution data from the College Scorecard API,
   filters to dual ED+CHEA-accredited / non-profit / non-religious / non-arts institutions, then
   (via a slow, agentic Step 5) finds each institution's library resource-list page. Needs
   `credentials.json` at this repo's root. Produces
   `output/accredited_nonprofit_secular_institutions.xlsx`.
2. **`institution-resource-list-cleanup`** — post-processes that spreadsheet: a stricter
   religious-institution filter pass, and de-duplication down to one row per unique resource URL
   (many institutions share the same library page). Produces
   `output/accredited_nonprofit_secular_institutions_unique_resource_urls.xlsx`.
3. **`resource-url-verification`** — checks every resource URL for a real HTTP 200 and for "soft
   404s" (a 200 response that's actually a not-found page). Produces
   `output/unique_resources_checked.xlsx`, then `output/unique_resources_double_checked.xlsx` (a
   slower recheck pass targeted at whatever failed the first, faster pass).
4. **`nde-backlink-check`** — for every resource confirmed valid, searches that resource's site for
   a link to the NIAID Data Ecosystem (`https://data.niaid.nih.gov`). Runs independently of the
   other three (does its own reachability check if pointed at a spreadsheet that hasn't been through
   step 3). Produces a dated file, `output/<YYYY-MM-DD>_unique_resources_backlink_check.xlsx`, so
   re-running it later to compare backlink coverage over time never overwrites an earlier run.

Each stage reads the previous stage's output and writes its own new file — nothing in `output/`
gets overwritten by a later stage (see each skill's own `SKILL.md` for exceptions and specifics,
e.g. `resource-url-verification`'s two files *do* refresh in place on repeat runs of that same
skill, by design).

## `output/`

Holds every spreadsheet produced by the pipeline, plus `STEP5_SESSION_NOTES.md` (a running log of
non-obvious decisions, filter false-negatives found along the way, and file-rename history — read
this for context before assuming a filename or row count is still current). Checkpoint files
(`*checkpoint*.json`) and point-in-time snapshots (`snapshot_*.xlsx`) are gitignored; the working
spreadsheets are not.
