# lazytwister

A lazygit-style terminal UI for running Zephyr **twister** tests in a **west** workspace.

```
┌[1] Tests ───────────────────────────────┐┌[3] Jobs ─────────────────────────────┐
│ ▾ ✘ tests/  1/1/10                      ││ ⠹ #3 lib/                 4/7  12s   │
│   ▾ ✘ drivers/  0/1/2                   ││ … #4 drivers.beta         queued 1   │
│     ▸ ✘ drivers.gpio.2pin               ││ ✔ #1 libraries.encoding.json     8s  │
│   ▾ ✔ lib/  1/0/6                       │├[4] Output ───────────────────────────┤
│     ▾ ✔ libraries.encoding.json         ││ $ west twister -T … -s … -G -i -v …  │
│         ✔ lib_json_test.json_encoding   ││ INFO - 1/1 native_sim/native/64 …    │
│   ▸ · subsys/  0/0/2                    │├[5] Details ──────────────────────────┤
│                                         ││ scenario  libraries.encoding.json    │
│                                         ││ last results / failing cases / log   │
└─────────────────────────────────────────┘└──────────────────────────────────────┘
 zephyrproject · tests · default platforms · -G · 12 scenarios 1/1/10
```

## About

> **Disclaimer:** lazytwister is a side project, built mainly to find out what I can make
> with [Claude Code](https://claude.com/claude-code). Nearly all of the code was written by
> Claude, with me steering, testing and deciding what to build. It works well for me, but
> treat it as an experiment rather than a polished, supported tool.

I use [lazygit](https://github.com/jesseduffield/lazygit) every day and love how it turns
a command line tool into something you can see and drive with a few keys. Running Zephyr
tests with twister is the opposite: long command lines, scrolling through output to find
what failed, and re-typing `-s`/`-T` arguments to rerun one test. So I wanted the same
kind of tool for twister: see all the tests at a glance, queue them with a keypress, keep
the results around, and jump straight to the assert that failed.

## Features

- **Discovery**: finds every `testcase.yaml` / `sample.yaml` scenario under the test
  roots and every `ZTEST*()` case in their sources, shown as a folder → scenario → case tree.
  Folders show `passed/failed/not run` counts in green/red/blue; "not run" covers
  skipped, filtered, build-only, queued and never-run scenarios.
  Big roots like `zephyr/tests` stay responsive: tests load in the background with a
  spinner, large trees start with only the roots open, and a folder's contents are only
  built when you expand it.
- **Choose the test folders**: the first time you start lazytwister in a directory, a
  folder browser opens so you can pick which folders to look for tests in. Each folder
  shows how many `testcase.yaml` / `sample.yaml` files it holds. The choice is
  remembered for that directory; press `O` to change it from inside the app.
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

### Install script (any Linux)

```sh
curl -fsSL https://raw.githubusercontent.com/hansbinderup/lazytwister/main/install.sh | bash
```

This needs Python 3.11 or newer with the `venv` module (on Debian/Ubuntu:
`sudo apt install python3-venv`). No root is needed. The script:

- creates a virtualenv in `~/.local/share/lazytwister` and installs lazytwister and its
  dependencies (textual, watchfiles, PyYAML) from PyPI into it
- links the `lazytwister` command into `~/.local/bin` (and tells you if that isn't on
  your `PATH`)

Run it again to update; if an update fails, the current install is left as it was. To install a branch, tag or commit, set `LAZYTWISTER_REF`:

```sh
curl -fsSL https://raw.githubusercontent.com/hansbinderup/lazytwister/main/install.sh | LAZYTWISTER_REF=v0.1.0 bash
```

Other overrides: `PYTHON` (interpreter to use), `LAZYTWISTER_HOME` (install directory) and
`LAZYTWISTER_BIN_DIR` (where the command is linked).

While the repo is private, `curl` can't download from it. Clone it and run the script
from the clone instead; it then installs from the clone:

```sh
git clone git@github.com:hansbinderup/lazytwister.git && ./lazytwister/install.sh
```

To uninstall:

```sh
curl -fsSL https://raw.githubusercontent.com/hansbinderup/lazytwister/main/uninstall.sh | bash
# or from a clone: ./uninstall.sh
```

This removes the virtualenv and the `~/.local/bin/lazytwister` link. Your test results,
twister build output and remembered test folders in `~/.cache/lazytwister` are kept; add
`--purge` to remove them too (`… | bash -s -- --purge`, or `./uninstall.sh --purge`).

### With Nix

The repo is a flake (needs flakes enabled: `experimental-features = nix-command flakes`).
While the repo is private, Nix needs a GitHub token to fetch it: add
`access-tokens = github.com=<token>` to `~/.config/nix/nix.conf`, or use a clone (`.`).

Try it without installing:

```sh
nix run github:hansbinderup/lazytwister
```

Install it into your profile, and upgrade later:

```sh
nix profile install github:hansbinderup/lazytwister   # Nix >= 2.27 also accepts: nix profile add
nix profile upgrade lazytwister
```

From a local checkout, use `.` (or the path to it) instead of `github:hansbinderup/lazytwister`.
Nix only sees files tracked by git, so `git add` new files before building.

On NixOS or with home-manager, add it as a flake input:

```nix
# flake.nix
inputs.lazytwister.url = "github:hansbinderup/lazytwister";

# configuration.nix (NixOS)             or home.nix (home-manager)
environment.systemPackages = [          # home.packages = [
  inputs.lazytwister.packages.${pkgs.stdenv.hostPlatform.system}.default
];
```

Pass `inputs` to your modules with `specialArgs` (NixOS) or `extraSpecialArgs` (home-manager).
To pin a branch, tag or commit: `github:hansbinderup/lazytwister/<ref>`.

Inside a workspace that has its own flake, you can also add lazytwister to that flake's dev
shell (`packages = [ inputs.lazytwister.packages.${system}.default ];`), so it's on `PATH`
together with `west` and the SDK.

### With pip / uv

```sh
uv venv .venv && uv pip install -e '.[dev]'
```

### Running

Start it **from inside the workspace's dev shell**, so that `west` and the Zephyr
SDK are on `PATH`:

```sh
cd ~/zephyrproject && nix develop
lazytwister                # first time: asks which folders to use
lazytwister -T tests/lib -p native_sim/native/64 -j 8 -w lib -- --coverage
```

(With the uv install, run `~/repos/lazytwister/.venv/bin/lazytwister`.)

Arguments after `--` are passed to every twister invocation.

### Test folders

The test roots come from the first of these that is set:

1. `-T` on the command line
2. `roots` in `.lazytwister.toml`
3. the folders chosen in the folder browser for this directory

If none is set (the first start in a directory), the folder browser opens, with
`./tests` preselected if it exists. `esc` there uses that default for now and asks
again next time. `--pick-folders` opens the browser on start anyway.

In the browser, `space` selects a folder (everything under it is included), `enter`
applies and `esc` cancels. `[✔]` is a chosen folder, `[·]` is inside one, `[-]` contains
one. The choice is saved in the state dir (`folders.json`), not in your repo.

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
| `O` | choose the test folders (folder browser) |
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
# or with Nix:
nix develop -c python -m pytest   # dev shell with Python, the dependencies and pytest
nix build                       # builds the package and runs the tests; result in ./result
```

The tests use `tests/fake_twister.py` in place of twister, so they run without Zephyr.
