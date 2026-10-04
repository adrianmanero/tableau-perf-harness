# Tableau perf harness

Scripted, repeatable interaction benchmarks for a published Tableau view.
One scenario file per view. The runner and the report do not change between views.

Each step is timed until the Embedding API call resolves. That is the wait a person
sees on the published view, covering the server query and the render together.

## Why not Tableau Desktop's recorder

Tableau Desktop already has a performance recording: Help → Settings and Performance → Start Performance Recording, do the clicks, then stop. Use that when you need to explain one slow click. The recording splits the click into overlapping events (the query, connecting, client-side sorting, layout). Those rows nest, so adding them up is not the time a person waited. The number they felt is the top-level command.

This harness answers a different question: is the published view faster for a fixed series of interactions? It opens the view in a browser, runs the same written steps for several passes, leaves the warmup pass out of the median, and compares two result files by step label. A Desktop recording does not do that. It measures Desktop opening a workbook on that machine, the clicks are whatever happened during that one session, and nothing is stored that you can rerun against the other workbook.

Use a Desktop recording to explain a slow step. Use this harness to decide whether a published change is faster. It does not separate query time from render time, and it does not measure warehouse cost.

## Setup

```bash
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium
cp config.example.yaml config.yaml
```

Edit `server` and `site` in `config.yaml`. That file is gitignored.

## Configuration

`config.yaml` holds the Tableau server and the defaults shared by scenarios. Copy `config.example.yaml`.

```yaml
server: https://your-pod.online.tableau.com
site: your-site
warmup_passes: 1
passes: 3
step_gap_ms: 500
interactive_timeout_s: 300
timeout_s: 3600
headless: false
viewport:
  width: 1920
  height: 1080
```

A scenario can then name the view:

```yaml
view: Workbook/Overview
```

That is opened as `https://your-pod.online.tableau.com/t/your-site/views/Workbook/Overview`. A full `view_url` in the scenario is used as written. The same key in the scenario wins over `config.yaml`. A command-line flag (`--timeout`, `--width`, `--height`, `--headless`, `--headed`) wins over both. `TABLEAU_PERF_PROFILE` wins over `profile` in the config.

The runner reads `./config.yaml`, then `config.yaml` in the repo root. `--config path` selects a file.

## Run

```bash
python3 run.py scenarios/local/baseline.yaml
```

Copy `examples/baseline.yaml` into `scenarios/local/` and point it at your view. The first run opens a window. Sign in there if the view asks. The session stays in `~/.cache/tableau-perf-profile`, so later runs can pass `--headless`.

```bash
python3 run.py --clear-session          # delete the stored session and exit
python3 run.py examples/baseline.yaml --dry-run   # resolve dates, do not open a browser
```

Set `TABLEAU_PERF_PROFILE` to keep that session somewhere else. Do not point it
at a directory inside this repo: the profile holds sign-in cookies.

Results go to `results/<scenario>_<view>_<timestamp>.json`.

## Compare

```bash
python3 run.py scenarios/local/baseline.yaml
python3 run.py scenarios/local/candidate.yaml
python3 report.py results/baseline_<view>_<ts>.json results/candidate_<view>_<ts>.json
```

`report.py` prints median, mean, and p95 for measured passes. Warmup passes are
shown and left out of those stats. The delta table matches steps by label, so
the two scenarios need the same labels. A then B: a negative delta means B is faster.

```bash
python3 report.py examples/sample_baseline.json examples/sample_candidate.json
python3 report.py results/baseline.json --format json
python3 report.py results/baseline.json results/candidate.json --format csv
```

The files in `examples/sample_*.json` are synthetic. They only show the report layout.

`python3 -m tableau_perf run …` and `python3 -m tableau_perf report …` call the same code.

## Writing a scenario

A scenario is one YAML (or JSON) file. The `steps` list is the script: each item is one action, run in order, once per pass. `examples/baseline.yaml` is a complete file.

```yaml
name: baseline              # optional label stored with the run
view: Workbook/Sheet        # joined with server and site from config.yaml
# view_url: https://...     # or a full URL, which is used as written
warmup_passes: 1            # recorded, excluded from median/mean/p95
passes: 3                   # measured repetitions of the whole step list
step_gap_ms: 500            # pause between steps, not included in the timing
interactive_timeout_s: 300  # how long `load` waits for the view
steps:
  - action: load
    label: "load view"
  - action: parameter
    name: Start Date
    value: "{today-7d}"
    label: "param: Start Date -> 7 days ago"
```

`label` is what shows up in the report. Two scenarios only compare cleanly when their labels match, so keep the step list and the labels the same on both sides of an A/B pair and change the view URL.

`name`, `field`, and `sheet` are the captions on the published view: parameter names, field names, and worksheet names as a person sees them.

A browser URL (`…/#/site/<site>/views/…`) is rewritten to the embed form (`…/t/<site>/views/…`). Query parameters whose names look like a token, ticket, or password are removed and never written into the result file.

`value` and entries in `values` may be date tokens, resolved to `YYYY-MM-DD` when the run starts: `{today}`, `{today-7d}`, `{today-1m}`, `{year-start}`, `{year-start-1y}`, `{year-start-2y+1d}`. Anything else is sent through as written. Check the resolved file with `--dry-run` before a real run.

The whole step list runs `warmup_passes + passes` times. Start the list with `load` when each pass should open a fresh view. Without that, the next pass continues from the view left open by the previous one. A failed step is recorded and the run continues. `--fail-on-step-error` exits non-zero in that case. If `load` never becomes interactive, the run exits non-zero either way.

`load` starts a new session, and `refresh` bypasses the data cache. Warmth left on the server by other people is outside this tool. Interleave the two sides of an A/B pair. When `warmup_passes` is 0, the first measured pass is also reported as `cold p1`.

## Actions

| Action | Required | What it does | Timed |
|---|---|---|---|
| `load` | — | Embeds the view URL and waits until it is first interactive. A later `load` throws the previous embed away and starts a new session. | yes |
| `refresh` | — | Requeries the data for the current view, bypassing the data cache. | yes |
| `tab` | `name` | Switches to that dashboard sheet. | yes |
| `parameter` | `name`, `value` | Sets one parameter. | yes |
| `filter` | `field`, and `values` or `value` | Applies a categorical filter. | yes |
| `clear_filter` | `field` | Clears that filter. | yes |
| `select_marks` | `sheet`, `field`, and `values` or `value` | Selects marks, which fires the same dashboard actions as a click. | yes |
| `clear_selection` | `sheet` | Clears the mark selection on that worksheet. | yes |
| `pause` | — | Waits `ms` milliseconds (default 1000). Use it to let a dashboard settle. | no |

`filter` and `clear_filter` take an optional `sheet`. Without it, the action is applied to every worksheet on the active dashboard that has the field, and worksheets that lack the field are skipped. With `sheet`, that worksheet must accept the field or the step fails. `filter` also takes `mode`: `replace` (default), `add`, `remove`, or `all`.

```yaml
- action: filter
  field: Category
  values: ["Example"]
  label: "filter: Category -> Example"

- action: filter
  sheet: Sales by region
  field: Region
  values: ["North"]
  mode: add
  label: "filter: Region add North on Sales by region"

- action: select_marks
  sheet: Sales by region
  field: Region
  values: ["North"]
  label: "select: Region North"

- action: pause
  ms: 2000
```

## AI agents

For an AI agent, follow `AGENTS.md`. It explains how to turn a written walkthrough into a scenario file.
