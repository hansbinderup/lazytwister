# lazytwister

A lazygit-style terminal UI for running Zephyr **twister** tests in a **west** workspace.

```
┌[1] Tests ───────────────────────────────┐┌[3] Jobs ─────────────────────────────┐
│ ▾ ✘ tests/  1/12 ✘1                     ││ ⠹ #3 lib/                 4/7  12s   │
│   ▾ ✘ drivers/  0/3 ✘1                  ││ … #4 drivers.beta         queued 1   │
│     ▸ ✘ drivers.gpio.2pin               ││ ✔ #1 libraries.encoding.json     8s  │
│   ▾ ✔ lib/  1/7                         │├[4] Output ───────────────────────────┤
│     ▾ ✔ libraries.encoding.json         ││ $ west twister -T … -s … -G -i -v …  │
│         ✔ lib_json_test.json_encoding   ││ INFO - 1/1 native_sim/native/64 …    │
│   ▸ · subsys/  0/2                      │├[5] Details ──────────────────────────┤
│                                         ││ scenario  libraries.encoding.json    │
│                                         ││ last results / failing cases / log   │
└─────────────────────────────────────────┘└──────────────────────────────────────┘
 zephyrproject · tests · default platforms · -G · 12 scenarios ✔1 ✘1
```

## Features

- **Discovery**: finds every `testcase.yaml` / `sample.yaml` scenario under the test
  roots and every `ZTEST*()` case in their sources, shown as a folder → scenario → case tree.
- **Live reload**: the tree updates as soon as tests are added, removed or changed
  (via `watchfiles`). Keep it open next to your editor.
- **Run anything**: a folder (`twister -T`), one scenario (`-s`), or a single ztest case
  (`-- -test=suite::test`, native targets).
- **Job queue**: only one twister job runs at a time, so runs never compete for CPU.
  Twister still parallelises the builds within a job.
  - `enter` adds the node under the cursor to the queue. Mark several nodes with `space`,
    then `r` queues them all as **one** job (a single twister invocation).
  - In the Jobs panel, the running job is listed first, then the queue in execution order,
    then finished jobs. `x` cancels the selected job, queued or running, and `J`/`K`
    move a queued job later or earlier. `ctrl+x` clears the whole queue and stops the
    running job.
  - The next job only starts once the previous twister process has fully exited,
    including after a cancel.
- **Results** are kept across runs (per scenario and platform), with failing cases and
  log tails shown in the details panel. `F` queues everything that failed, and `.` repeats
  the last run.
- **Jump to the failure**: lazytwister reads where each failed assertion happened (file,
  line and message) from the test log, and shows it in Details. Press `e` on a failed case
  or scenario to open `$EDITOR` at the failing `zassert`.
- **Auto-run** (`w`): when a file changes, lazytwister reruns the scenarios it belongs to.
  For a change outside a test directory (any path passed with `-w`), it repeats the last run.

## Adaptive layout

The layout follows the terminal size and switches live as you resize or split panes:

- **Landscape** (wide terminals): two columns, as above.
- **Portrait** (fewer than 110 columns, or fewer columns than twice the number of rows):
  the panels are stacked top to bottom, so long scenario names get the full width.
- **Compact** (small terminals): Details is hidden, and `5` opens it as a pop-up.

The status bar along the bottom always shows the workspace, test roots, platforms, `-G`,
auto-run and the pass/fail totals. `2` opens the full status as a pop-up.

`v` overrides the automatic choice, and `z` maximises the focused panel.

## Install

```sh
uv venv .venv && uv pip install -e '.[dev]'   # or: nix develop / nix build
```

Then start it **from inside the workspace's dev shell**, so that `west` and the Zephyr
SDK are on `PATH`:

```sh
cd ~/zephyrproject && nix develop
~/repos/lazytwister/.venv/bin/lazytwister                # defaults to ./tests
lazytwister -T tests/lib -p native_sim/native/64 -j 8 -w lib -- --coverage
```

Arguments after `--` are passed to every twister invocation.

### Per-workspace config

Put a `.lazytwister.toml` in your workspace, so running it there needs no flags.
lazytwister looks in the current directory and its parents, up to the west workspace
root. Command line options override the file, and `--no-config` ignores it.

```toml
roots = ["tests"]              # relative to this file
platforms = ["native_sim/native/64"]
integration = true             # pass -G
verbose = true                 # pass -v (live per-scenario status)
auto_run = false
watch = ["lib", "subsys"]      # extra paths that trigger auto-run
twister = "west twister"
jobs = 8                       # twister -j
extra_args = ["--coverage"]
```

Unknown keys and wrong types are rejected with a clear error.

> Dev shells usually export a `PYTHONPATH` pointing at their own Python's packages.
> lazytwister ignores it for its own imports, so the dev shell's packages can't shadow
> lazytwister's dependencies. The variable is still passed on to twister. Set
> `LAZYTWISTER_KEEP_PYTHONPATH=1` to disable this.

### As `west tui`

West extension commands must come from a project in the manifest. Add lazytwister to
your `west.yml`:

```yaml
    - name: lazytwister
      path: tools/lazytwister
      url: <git remote of this repo>
      west-commands: west-commands.yml
```

Its Python dependencies must also be installed in west's environment.

## Keys

| Key | Action |
| --- | --- |
| `1`, `3`–`5`, `tab` | focus a panel |
| `2` | full status pop-up |
| `enter` | queue the node under the cursor |
| `space` / `c` | mark or unmark a node / clear all marks |
| `r` | queue the marked nodes as one job |
| `a` / `F` / `.` | queue all / queue failed / repeat the last run |
| `p` / `g` | choose platforms / toggle integration mode `-G` |
| `w` | toggle auto-run on file change |
| `/` / `f` | filter / show failed only |
| `e` | open `$EDITOR` at the failing assert, else at the test source or yaml |
| Jobs panel: `x` / `J` `K` | cancel the selected job / move a queued job later or earlier |
| Jobs panel: `r` / `L` | requeue the job / clear finished jobs |
| `ctrl+x` / `ctrl+r` | clear the queue and stop the running job / rediscover tests |
| `z` | maximise / restore the focused panel |
| `v` | layout: auto → landscape → portrait |
| `C` | clear the cache |
| `?` / `q` | help / quit (asks first if a job is running or queued) |

## Where things go

Results and twister output are stored in `~/.cache/lazytwister/<workspace>/` (override
with `--state-dir`). Nothing is written into your repo. All jobs share a single `run`
output directory, which lazytwister tells twister to delete at the start of each job
(`--clobber-output`). The cache therefore only ever holds the last job's builds, unless
you pass `-n/--no-clean`.

To free up space:

| Where | What it deletes |
| --- | --- |
| `C` in the app | twister build output, optionally the results history too (asks first) |
| `lazytwister --cache-info` | nothing; shows the space used per workspace |
| `lazytwister --clear-cache` | twister build output for this workspace; results are kept |
| `lazytwister --clear-cache all` | everything lazytwister stored, for every workspace |

Clearing only removes files lazytwister creates (`run*` build folders and `results.json`),
and never follows symlinks.

## Development

```sh
.venv/bin/pytest
```

The tests use `tests/fake_twister.py` in place of twister, so they run without Zephyr.
