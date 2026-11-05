# lazywest

A lazygit-style terminal UI for running Zephyr **twister** tests in a **west** workspace.

```
┌[1] Tests ───────────────────────────────┐┌[3] Jobs ─────────────────────────────┐
│ ▾ ✘ tests/  1/12 ✘1                     ││ ⠹ #3 lib/                 4/7  12s   │
│   ▾ ✘ drivers/  0/3 ✘1                  ││ ✘ #2 drivers.hw_…shell    1/1   9s   │
│     ▸ ✘ drivers.gpio.2pin               ││ ✔ #1 libraries.encoding.json     8s  │
│   ▾ ✔ lib/  1/7                         │├[4] Output ───────────────────────────┤
│     ▾ ✔ libraries.encoding.json         ││ $ west twister -T … -s … -G -i -v …  │
│         ✔ lib_json_test.json_encoding   ││ INFO - 1/1 native_sim/native/64 …    │
├[2] Status ──────────────────────────────┤├[5] Details ──────────────────────────┤
│ platforms  twister default              ││ scenario  libraries.encoding.json    │
│ parallel   2 jobs (1 running, 0 queued) ││ last results / failing cases / log   │
└─────────────────────────────────────────┘└──────────────────────────────────────┘
```

## Features

- **Discovery**: finds every `testcase.yaml` / `sample.yaml` scenario under the test
  roots and every `ZTEST*()` case in their sources, shown as a folder → scenario → case tree.
- **Live reload**: the tree updates as soon as tests are added, removed or changed
  (via `watchfiles`). Keep it open next to your editor.
- **Run anything**: a folder (`twister -T`), one scenario (`-s`), or a single ztest case
  (`-- -test=suite::test`, native targets).
- **Parallel**:
  - `space` marks several nodes. `r` runs them in **one** twister invocation, and twister
    parallelises the builds itself.
  - `R` runs each marked node as a **separate job**. Jobs are queued and up to
    `--parallel` run at once (`+`/`-` to change it). Each job gets its own output
    directory, and twister's `-j` is split between jobs.
- **Results** are kept across runs (per scenario and platform), with failing cases and
  log tails shown in the details panel. `F` reruns everything that failed.
- **Auto-run** (`w`): when a file changes, lazywest reruns the scenarios it belongs to.
  For a change outside a test directory (any path passed with `-w`), it repeats the last run.

## Install

```sh
uv venv .venv && uv pip install -e '.[dev]'   # or: nix develop / nix build
```

Then start it **from inside the workspace's dev shell**, so that `west` and the Zephyr
SDK are on `PATH`:

```sh
cd ~/zephyrproject && nix develop
~/repos/lazywest/.venv/bin/lazywest                # defaults to ./tests
lazywest -T tests/lib -p native_sim/native/64 -P 3 -w lib -- --coverage
```

Arguments after `--` are passed to every twister invocation.

> Dev shells usually export a `PYTHONPATH` pointing at their own Python's packages.
> lazywest ignores it for its own imports, so the dev shell's packages can't shadow
> lazywest's dependencies. The variable is still passed on to twister. Set
> `LAZYWEST_KEEP_PYTHONPATH=1` to disable this.

### As `west tui`

West extension commands must come from a project in the manifest. Add lazywest to
your `west.yml`:

```yaml
    - name: lazywest
      path: tools/lazywest
      url: <git remote of this repo>
      west-commands: west-commands.yml
```

Its Python dependencies must also be installed in west's environment.

## Keys

| Key | Action |
| --- | --- |
| `1`–`5`, `tab` | focus a panel |
| `enter` | run the node under the cursor |
| `space` / `c` | mark or unmark a node / clear all marks |
| `r` / `R` | run marked nodes as one job / as parallel jobs |
| `a` / `F` | run all / rerun failed |
| `p` / `g` | choose platforms / toggle integration mode `-G` |
| `+` / `-` | more / fewer parallel jobs |
| `w` | toggle auto-run on file change |
| `/` / `f` | filter / show failed only |
| `e` | open the yaml or test source in `$EDITOR` |
| Jobs panel: `x` / `r` / `L` | cancel / rerun / clear finished jobs |
| `ctrl+x` / `ctrl+r` | cancel all jobs / rediscover tests |
| `?` / `q` | help / quit |

## Where things go

Results and twister output are stored in `~/.cache/lazywest/<workspace>/` (override
with `--state-dir`). Nothing is written into your repo. There is one `run-N` directory
per parallel slot, and twister cleans it before reusing it.

## Development

```sh
.venv/bin/pytest
```

The tests use `tests/fake_twister.py` in place of twister, so they run without Zephyr.
