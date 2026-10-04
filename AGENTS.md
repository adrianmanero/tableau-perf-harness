# Building a scenario from a user's notes

Read this when someone describes a dashboard in their own words and wants a scenario file. The action reference and the timing rules are in `README.md`. Follow them. Do not invent a new action.

## What you are given

The user describes what they do on a published view: which sheet they open, which parameters they change, which filters they set, and which two versions they want to compare. That prose is the source of truth. A sentence they did not write is not a step.

They may also have `config.yaml` (from `config.example.yaml`) with `server` and `site`. Read it. Do not ask them to paste the server into every scenario when it is already there.

## What you write

One YAML file per view, under `scenarios/local/`. Those files stay untracked. Use `view: Workbook/Sheet` so the server and site come from `config.yaml`. Use a full `view_url` only when they pasted one.

For an A/B comparison, write two files. The step list and the `label` on every step must be identical. Only `view` (or `view_url`) and `name` change.

Start the list with `load` so each pass opens a fresh view. Then the interactions, in the order they described. Set `label` to a short description of that step (`filter: Category -> North`). The report matches on the label.

Omit `warmup_passes`, `passes`, `step_gap_ms`, and `interactive_timeout_s` when `config.yaml` already has the values they want.

After writing the file, show them the YAML and this check:

```bash
python3 run.py scenarios/local/<file>.yaml --dry-run
```

Run that yourself when the file is on disk. Fix date tokens and missing fields before telling them to open a browser.

## Turning their words into actions

| They said | Action |
|---|---|
| Open the view, load the dashboard | `load` |
| Go to a tab or sheet named in their notes | `tab` with that `name` |
| Change a parameter | `parameter` with `name` and `value` |
| A date such as today, last week, start of this year | a date token: `{today}`, `{today-7d}`, `{today-1m}`, `{year-start}`, `{year-start-1y}`, `{year-start-2y+1d}` |
| Filter a field to one or more values | `filter` with `field` and `values` |
| Filter on one worksheet only | same, plus `sheet` |
| Add to the current filter instead of replacing it | `filter` with `mode: add` |
| Clear a filter | `clear_filter` |
| Click a mark so a dashboard action runs | `select_marks` with `sheet`, `field`, and `values` |
| Clear that selection | `clear_selection` with `sheet` |
| Requery, bypass cache | `refresh` |
| Wait, with no measurement | `pause` with `ms` |

`name`, `field`, and `sheet` are the captions on the published view. Copy them from the user's notes. If they say "the date filter" and never give the caption, ask which name is on screen. Do not guess `Start Date`, a worksheet name, or a filter value.

Do not add a filter, a parameter, or a second sheet they did not mention. Do not drop a step they did mention.

## Before you finish

- The scenario has `steps`, and either `view` or `view_url`.
- Every `filter` and `select_marks` has `values` or `value`.
- Both sides of a comparison share labels.
- The file is under `scenarios/local/`, not `examples/`.
- `config.yaml` is the local server file. Do not commit it, and do not copy real view URLs into `examples/` or `README.md`.
