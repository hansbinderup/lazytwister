"""Command line entry point (`lazywest` and `west tui`)."""

from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
from pathlib import Path

from .discovery import default_roots, find_workspace
from .jobs import RunOptions


def default_state_dir(anchor: Path) -> Path:
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", str(anchor.resolve())).strip("_")
    return cache / "lazywest" / slug


def default_twister_cmd(zephyr_base: Path | None) -> list[str]:
    if shutil.which("west"):
        return ["west", "twister"]
    if zephyr_base and (zephyr_base / "scripts" / "twister").is_file():
        return ["python3", str(zephyr_base / "scripts" / "twister")]
    return ["west", "twister"]


def build_parser(prog: str = "lazywest") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="lazygit-style TUI for running Zephyr twister tests in a west workspace.",
        epilog="Arguments after '--' are passed to every twister invocation.",
    )
    add_arguments(parser)
    return parser


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-T", "--testsuite-root", action="append", type=Path, default=[],
                        help="test root to discover/run (repeatable; default: ./tests or .)")
    parser.add_argument("-p", "--platform", action="append", default=[],
                        help="twister platform (repeatable; default: twister's defaults)")
    parser.add_argument("--no-integration", action="store_true",
                        help="don't pass -G (integration mode) to twister")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="don't pass -v to twister (disables live per-scenario status)")
    parser.add_argument("-P", "--parallel", type=int, default=2,
                        help="max concurrently running twister jobs (default: 2)")
    parser.add_argument("-j", "--jobs", type=int, default=None,
                        help="twister -j per job (default: CPUs / --parallel)")
    parser.add_argument("-w", "--watch", action="append", type=Path, default=[],
                        help="extra path to watch for changes (repeatable), e.g. lib/")
    parser.add_argument("--auto-run", action="store_true",
                        help="start with auto-run on file change enabled")
    parser.add_argument("--twister", default=None,
                        help="twister command (default: 'west twister')")
    parser.add_argument("--state-dir", type=Path, default=None,
                        help="where results and twister output go "
                             "(default: ~/.cache/lazywest/<workspace>)")


def config_from_args(args: argparse.Namespace, extra: list[str]):
    from .app import AppConfig

    cwd = Path.cwd()
    workspace = find_workspace(cwd)
    roots = [r.resolve() for r in args.testsuite_root] or default_roots(cwd)
    missing = [r for r in roots if not r.is_dir()]
    if missing:
        raise SystemExit(f"lazywest: test root does not exist: {missing[0]}")
    if args.parallel < 1:
        raise SystemExit("lazywest: --parallel must be >= 1")
    if args.jobs is not None and args.jobs < 1:
        raise SystemExit("lazywest: --jobs must be >= 1")
    twister = shlex.split(args.twister) if args.twister else default_twister_cmd(
        workspace.zephyr_base
    )
    return AppConfig(
        cwd=cwd,
        roots=roots,
        workspace=workspace,
        twister_cmd=twister,
        state_dir=(args.state_dir or default_state_dir(workspace.topdir or cwd)).resolve(),
        options=RunOptions(
            platforms=args.platform,
            integration=not args.no_integration,
            verbose=not args.quiet,
            extra_args=extra,
            jobs=args.jobs,
        ),
        max_parallel=args.parallel,
        watch_paths=[w.resolve() for w in args.watch],
        auto_run=args.auto_run,
    )


def split_extra(argv: list[str]) -> tuple[list[str], list[str]]:
    if "--" in argv:
        index = argv.index("--")
        return argv[:index], argv[index + 1:]
    return argv, []


def run(args: argparse.Namespace, extra: list[str]) -> None:
    from .app import LazyWestApp

    LazyWestApp(config_from_args(args, extra)).run()


def main(argv: list[str] | None = None) -> None:
    import sys

    own, extra = split_extra(list(sys.argv[1:] if argv is None else argv))
    args = build_parser().parse_args(own)
    run(args, extra)


if __name__ == "__main__":
    main()
