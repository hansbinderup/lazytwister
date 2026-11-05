"""The lazytwister Textual application."""

from __future__ import annotations

import asyncio
import os
import shlex
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Footer, Input, OptionList, RichLog, SelectionList, Static, Tree
from textual.widgets.option_list import Option
from textual.widgets.tree import TreeNode

from .discovery import Discovery, Scenario, Workspace, discover
from .jobs import Job, JobManager, NodeRef, RunOptions, RunTarget, make_target
from .results import ResultStore, worst

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
STATUS_ICON = {
    "passed": ("✔", "green"),
    "failed": ("✘", "red"),
    "error": ("!", "bold red"),
    "blocked": ("⊘", "red"),
    "skipped": ("○", "bright_black"),
    "filtered": ("○", "bright_black"),
    "not run": ("◇", "cyan"),  # built but not executed (build_only / no runner)
    "queued": ("…", "yellow"),
    "cancelled": ("⊘", "bright_black"),
    None: ("·", "bright_black"),
}
JOB_ICON = {
    "queued": ("…", "yellow"),
    "passed": ("✔", "green"),
    "failed": ("✘", "red"),
    "error": ("!", "bold red"),
    "cancelled": ("⊘", "bright_black"),
}
WATCH_IGNORE_PARTS = {".git", ".lazytwister", "build", "__pycache__", ".venv"}
WATCH_IGNORE_SUFFIXES = (".swp", ".swx", ".tmp", "~", ".pyc")


@dataclass
class AppConfig:
    cwd: Path
    roots: list[Path]
    workspace: Workspace
    twister_cmd: list[str]
    state_dir: Path
    options: RunOptions = field(default_factory=RunOptions)
    max_parallel: int = 2
    watch_paths: list[Path] = field(default_factory=list)
    auto_run: bool = False


# --------------------------------------------------------------------------
# Widgets
# --------------------------------------------------------------------------


class TestTree(Tree[NodeRef]):
    BINDINGS = [
        Binding("enter", "app.run_cursor", "Run"),
        Binding("space", "app.toggle_mark", "Mark"),
        Binding("r", "app.run_marked", "Run marked"),
        Binding("R", "app.run_marked_parallel", "Run marked ∥"),
        Binding("c", "app.clear_marks", "Unmark", show=False),
        Binding("e", "app.edit", "Edit"),
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
        Binding("l,right", "expand", show=False),
        Binding("h,left", "collapse", show=False),
        Binding("o", "toggle_node", "Fold", show=False),
    ]

    def action_expand(self) -> None:
        node = self.cursor_node
        if node is None:
            return
        if node.allow_expand and not node.is_expanded:
            node.expand()
        elif node.children:
            self.move_cursor(node.children[0])

    def action_collapse(self) -> None:
        node = self.cursor_node
        if node is None:
            return
        if node.is_expanded:
            node.collapse()
        elif node.parent is not None and node.parent is not self.root:
            self.move_cursor(node.parent)


class JobList(OptionList):
    BINDINGS = [
        Binding("x", "app.cancel_job", "Cancel"),
        Binding("r", "app.rerun_job", "Rerun"),
        Binding("L", "app.clear_jobs", "Clear done"),
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
    ]


class FilterInput(Input):
    BINDINGS = [Binding("escape", "app.clear_filter", "Clear filter")]


class PlatformScreen(ModalScreen[list[str] | None]):
    BINDINGS = [
        Binding("escape", "dismiss_none", "Cancel"),
        Binding("enter,ctrl+s", "apply", "Apply", priority=True),
    ]

    def __init__(self, known: list[str], selected: list[str]):
        super().__init__()
        self.known = list(dict.fromkeys([*selected, *known]))
        self.selected = selected

    def compose(self) -> ComposeResult:
        with Vertical(id="platform-dialog", classes="panel") as dialog:
            dialog.border_title = "Platforms"
            dialog.border_subtitle = "space: toggle · enter: apply · esc: cancel"
            yield Static("None selected = twister defaults (plus -G integration platforms).")
            yield SelectionList[str](
                *[(p, p, p in self.selected) for p in self.known], id="platform-list"
            )
            yield Input(placeholder="other platforms, comma separated", id="platform-extra")

    def action_dismiss_none(self) -> None:
        self.dismiss(None)

    def action_apply(self) -> None:
        chosen = list(self.query_one(SelectionList).selected)
        extra = self.query_one("#platform-extra", Input).value
        chosen += [p.strip() for p in extra.split(",") if p.strip()]
        self.dismiss(list(dict.fromkeys(chosen)))


HELP_TEXT = """\
[b]Panels[/]   1 tests · 2 status · 3 jobs · 4 output · 5 details · tab cycles

[b]Tests[/]
  enter      run node under cursor (folder → whole folder, scenario, single ztest case)
  space      mark / unmark node (multi-select)
  r          run marked nodes in ONE twister invocation (twister parallelises internally)
  R          run each marked node as its OWN job (parallel job queue)
  c          clear marks
  e          open testcase.yaml / test source in $EDITOR
  h/l j/k    navigate, collapse / expand
  /          filter        f   only failed

[b]Global[/]
  a          run all test roots          F   rerun failed scenarios
  p          choose platforms            g   toggle integration mode (-G)
  + / -      more / fewer parallel jobs  w   toggle auto-run on file change
  ctrl+x     cancel all jobs             ctrl+r  rediscover tests
  q          quit

[b]Jobs[/]   x cancel · r rerun · L clear finished

Single ztest cases are filtered with the native_sim `-test=` option,
so they only narrow the run on native (posix) platforms.
"""


class HelpScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape,q,question_mark", "app.pop_screen", "Close")]

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help-dialog", classes="panel") as dialog:
            dialog.border_title = "Keybindings"
            yield Static(HELP_TEXT)


# --------------------------------------------------------------------------
# App
# --------------------------------------------------------------------------


class LazyTwisterApp(App):
    TITLE = "lazytwister"
    CSS = """
    Screen { layout: horizontal; }
    .panel {
        border: round $panel-lighten-2;
        border-title-color: $text-muted;
        border-subtitle-color: $text-muted;
        background: $surface;
    }
    .panel:focus, .panel:focus-within {
        border: round $success;
        border-title-color: $success;
        border-title-style: bold;
    }
    #left { width: 45%; min-width: 40; }
    #right { width: 1fr; }
    #tests-panel { height: 1fr; }
    #tests { border: none; background: $surface; padding: 0; }
    #filter { display: none; border: none; height: 1; padding: 0 1; }
    #filter.visible { display: block; }
    #status { height: auto; max-height: 12; padding: 0 1; }
    #jobs { height: 9; }
    #log { height: 1fr; }
    #details-panel { height: 40%; padding: 0 1; }
    #platform-dialog, #help-dialog {
        width: 80; max-width: 95%; height: auto; max-height: 85%;
        padding: 1 2; background: $surface;
    }
    PlatformScreen, HelpScreen { align: center middle; }
    #platform-list { height: auto; max-height: 20; margin: 1 0; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("question_mark", "help", "Help"),
        Binding("a", "run_all", "Run all"),
        Binding("F", "rerun_failed", "Rerun failed"),
        Binding("p", "platforms", "Platform"),
        Binding("g", "toggle_integration", "-G", show=False),
        Binding("w", "toggle_autorun", "Auto-run"),
        Binding("plus,equals_sign", "parallel(1)", "+jobs", show=False),
        Binding("minus", "parallel(-1)", "-jobs", show=False),
        Binding("slash", "filter", "Filter"),
        Binding("f", "toggle_failed_only", "Failed only", show=False),
        Binding("ctrl+x", "cancel_all", "Cancel all", show=False),
        Binding("ctrl+r", "rediscover", "Rediscover", show=False),
        Binding("1", "focus_panel('tests')", show=False),
        Binding("2", "focus_panel('status')", show=False),
        Binding("3", "focus_panel('jobs')", show=False),
        Binding("4", "focus_panel('log')", show=False),
        Binding("5", "focus_panel('details-panel')", show=False),
    ]

    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config
        self.options = config.options
        self.auto_run = config.auto_run
        self.discovery = Discovery(config.roots, [], {})
        self.store = ResultStore(config.state_dir / "results.json")
        self.jobs = JobManager(
            twister_cmd=config.twister_cmd,
            state_dir=config.state_dir,
            cwd=config.cwd,
            max_parallel=config.max_parallel,
            on_change=self._on_job_change,
            on_line=self._on_job_line,
            on_finished=self._on_job_finished,
        )
        self.marks: dict[str, NodeRef] = {}
        self.node_index: dict[str, TreeNode[NodeRef]] = {}
        self.folder_scenarios: dict[str, list[str]] = defaultdict(list)
        self.live: dict[str, str] = {}  # scenario -> queued/running/live result
        self.filter_text = ""
        self.failed_only = False
        self.viewed_job: int | None = None
        self.last_target: RunTarget | None = None
        self._tree_built = False
        self._dirty = False
        self._spin = 0

    # -- layout ------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Vertical(id="left"):
            with Vertical(id="tests-panel", classes="panel") as tests_panel:
                tests_panel.border_title = "[1] Tests"
                tree = TestTree("tests", id="tests")
                tree.show_root = False
                tree.auto_expand = False
                tree.guide_depth = 3
                yield tree
                yield FilterInput(placeholder="filter…", id="filter")
            status = Static(id="status", classes="panel")
            status.border_title = "[2] Status"
            status.can_focus = True
            yield status
        with Vertical(id="right"):
            jobs = JobList(id="jobs", classes="panel")
            jobs.border_title = "[3] Jobs"
            yield jobs
            log = RichLog(id="log", classes="panel", markup=False, highlight=False, wrap=False)
            log.border_title = "[4] Output"
            yield log
            with VerticalScroll(id="details-panel", classes="panel") as details:
                details.border_title = "[5] Details"
                yield Static(id="details")
        yield Footer()

    @property
    def tree(self) -> TestTree:
        return self.query_one("#tests", TestTree)

    async def on_mount(self) -> None:
        self.tree.focus()
        self.update_status()
        self.set_interval(0.15, self._tick)
        await self.rediscover()
        self.watch_files()

    # -- discovery & tree ----------------------------------------------------

    async def rediscover(self) -> None:
        self.discovery = await asyncio.to_thread(discover, self.config.roots)
        self.rebuild_tree()
        self.update_status()
        self.update_details()

    def _matches(self, scenario: Scenario) -> bool:
        if self.failed_only and self.status_of(scenario.name) not in ("failed", "error", "blocked"):
            return False
        if not self.filter_text:
            return True
        needle = self.filter_text.lower()
        haystack = [scenario.name, str(scenario.directory), *scenario.tags]
        haystack += [c.id for c in scenario.cases]
        return any(needle in h.lower() for h in haystack)

    def rebuild_tree(self) -> None:
        tree = self.tree
        expanded: set[str] | None = None
        cursor_key = None
        if self._tree_built:
            expanded = {k for k, n in self.node_index.items() if n.is_expanded}
            if tree.cursor_node is not None and tree.cursor_node.data is not None:
                cursor_key = tree.cursor_node.data.key

        tree.clear()
        self.node_index = {}
        self.folder_scenarios = defaultdict(list)

        def add(parent: TreeNode, ref: NodeRef, leaf: bool = False) -> TreeNode:
            if leaf:
                node = parent.add_leaf(self.label_for(ref), data=ref)
            else:
                default = ref.kind == "folder"
                is_open = default if expanded is None else ref.key in expanded
                node = parent.add(self.label_for(ref), data=ref, expand=is_open)
            self.node_index[ref.key] = node
            return node

        placed: set[str] = set()
        for root in self.discovery.roots:
            root_ref = NodeRef("folder", root)
            root_node = add(tree.root, root_ref)
            root_node.expand()
            folders = {root: root_node}

            def folder(path: Path) -> TreeNode:
                if path in folders:
                    return folders[path]
                parent = folder(path.parent)
                folders[path] = add(parent, NodeRef("folder", path))
                return folders[path]

            for scenario in self.discovery.scenarios:
                if scenario.name in placed:
                    continue
                if not (scenario.directory == root or root in scenario.directory.parents):
                    continue
                placed.add(scenario.name)
                if not self._matches(scenario):
                    continue
                parent = folder(scenario.directory)
                ref = NodeRef("scenario", scenario.directory, scenario.name)
                node = add(parent, ref, leaf=not scenario.cases)
                for case in scenario.cases:
                    add(node, NodeRef("case", scenario.directory, scenario.name, case), leaf=True)
                path = scenario.directory
                while True:
                    self.folder_scenarios[f"d:{path}"].append(scenario.name)
                    if path == root or path.parent == path:
                        break
                    path = path.parent

        # Drop marks for nodes that no longer exist.
        self.marks = {k: v for k, v in self.marks.items() if k in self.node_index}
        self._tree_built = True
        self.refresh_labels()
        if cursor_key and cursor_key in self.node_index:
            tree.move_cursor(self.node_index[cursor_key])

    # -- status helpers -----------------------------------------------------

    def status_of(self, scenario: str) -> str | None:
        return self.live.get(scenario) or self.store.scenario_status(scenario)

    def _icon(self, status: str | None) -> tuple[str, str]:
        if status == "running":
            return SPINNER[self._spin % len(SPINNER)], "yellow"
        return STATUS_ICON.get(status, STATUS_ICON[None])

    def label_for(self, ref: NodeRef) -> Text:
        text = Text()
        if ref.key in self.marks:
            text.append("◆ ", style="bold magenta")
        if ref.kind == "folder":
            names = self.folder_scenarios.get(ref.key, [])
            statuses = [self.status_of(n) for n in names]
            status = (
                "running" if "running" in statuses
                else "queued" if "queued" in statuses
                else worst(statuses)
            )
            icon, style = self._icon(status)
            text.append(f"{icon} ", style=style)
            text.append(f"{ref.path.name}/", style="bold")
            passed = statuses.count("passed")
            bad = sum(statuses.count(s) for s in ("failed", "error", "blocked"))
            counts = f"  {passed}/{len(names)}"
            text.append(counts, style="bright_black")
            if bad:
                text.append(f" ✘{bad}", style="red")
        elif ref.kind == "scenario":
            assert ref.scenario is not None
            icon, style = self._icon(self.status_of(ref.scenario))
            text.append(f"{icon} ", style=style)
            text.append(ref.scenario)
            scenario = self.discovery.by_name().get(ref.scenario)
            if scenario and scenario.build_only:
                text.append("  build-only", style="bright_black italic")
        else:
            assert ref.case is not None and ref.scenario is not None
            live = self.live.get(ref.scenario)
            status = live if live in ("running", "queued") else self.store.case_status(
                ref.scenario, ref.case.id
            )
            icon, style = self._icon(status)
            text.append(f"{icon} ", style=style)
            text.append(ref.case.suite, style="bright_black")
            text.append(".")
            text.append(ref.case.name)
        return text

    def refresh_labels(self, only_running: bool = False) -> None:
        for key, node in self.node_index.items():
            ref = node.data
            if ref is None:
                continue
            if only_running:
                names = (
                    self.folder_scenarios.get(key, []) if ref.kind == "folder" else [ref.scenario]
                )
                if not any(self.live.get(n) == "running" for n in names):
                    continue
            node.set_label(self.label_for(ref))

    def recompute_live(self) -> None:
        live: dict[str, str] = {}
        for job in self.jobs.jobs:
            if not job.active:
                continue
            for name in job.target.covered:
                state = job.live_status.get(name) or job.state
                if live.get(name) != "running":
                    live[name] = state
        self.live = live

    def _tick(self) -> None:
        self._spin += 1
        if self._dirty:
            self._dirty = False
            self.recompute_live()
            self.refresh_labels()
            self.refresh_jobs()
            self.update_status()
        elif self.jobs.running():
            self.refresh_labels(only_running=True)
            self.refresh_jobs()

    # -- panels ---------------------------------------------------------------

    def update_status(self) -> None:
        cfg = self.config
        on = Text("on", style="green")
        off = Text("off", style="bright_black")
        names = [s.name for s in self.discovery.scenarios]
        statuses = [self.store.scenario_status(n) for n in names]
        text = Text()

        def row(label: str, value) -> None:
            text.append(f"{label:<12}", style="bold")
            text.append(value if isinstance(value, Text) else Text(str(value)))
            text.append("\n")

        row("workspace", cfg.workspace.topdir or "(not in a west workspace)")
        row("roots", ", ".join(self._rel(r) for r in cfg.roots))
        row("platforms", ", ".join(self.options.platforms) or "twister default")
        row("integration", on if self.options.integration else off)
        row("auto-run", on if self.auto_run else off)
        row("parallel", f"{self.jobs.max_parallel} jobs  ({len(self.jobs.running())} running,"
            f" {len(self.jobs.queued())} queued)")
        cases = sum(len(s.cases) for s in self.discovery.scenarios)
        summary = Text(f"{len(names)} scenarios, {cases} cases  ")
        summary.append(f"✔{statuses.count('passed')} ", style="green")
        failed = sum(statuses.count(s) for s in ("failed", "error", "blocked"))
        summary.append(f"✘{failed}", style="red" if failed else "bright_black")
        row("tests", summary)
        if self.discovery.errors:
            row("yaml errors", Text(str(len(self.discovery.errors)), style="bold red"))
        text.rstrip()
        self.query_one("#status", Static).update(text)

    def _rel(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.config.cwd)) or "."
        except ValueError:
            return str(path)

    def refresh_jobs(self) -> None:
        job_list = self.query_one(JobList)
        options = []
        for job in reversed(self.jobs.jobs):
            if job.state == "running":
                icon, style = SPINNER[self._spin % len(SPINNER)], "yellow"
            else:
                icon, style = JOB_ICON.get(job.state, ("?", ""))
            prompt = Text()
            prompt.append(f"{icon} ", style=style)
            prompt.append(f"#{job.id} ", style="bright_black")
            prompt.append(job.target.title)
            if job.total:
                prompt.append(f"  {job.done}/{job.total}", style="cyan")
            if job.started_at:
                prompt.append(f"  {job.elapsed:.0f}s", style="bright_black")
            options.append(Option(prompt, id=str(job.id)))
        highlighted = self.viewed_job
        job_list.clear_options()
        job_list.add_options(options)
        if highlighted is not None:
            for index, job in enumerate(reversed(self.jobs.jobs)):
                if job.id == highlighted:
                    job_list.highlighted = index
                    break
        job_list.border_subtitle = (
            f"{len(self.jobs.running())}/{self.jobs.max_parallel} running"
            if self.jobs.jobs else ""
        )

    def show_job_log(self, job: Job | None) -> None:
        log = self.query_one("#log", RichLog)
        log.clear()
        if job is None:
            log.border_title = "[4] Output"
            return
        self.viewed_job = job.id
        log.border_title = f"[4] Output — #{job.id} {job.target.title}"
        for line in job.lines[-5000:]:
            log.write(Text.from_ansi(line))

    def update_details(self) -> None:
        details = self.query_one("#details", Static)
        node = self.tree.cursor_node
        ref = node.data if node is not None else None
        if ref is None:
            text = Text("Select a test.", style="bright_black")
            if self.discovery.errors:
                text = Text()
                text.append("YAML parse errors\n", style="bold red")
                for path, error in self.discovery.errors.items():
                    text.append(f"{self._rel(path)}: ", style="bold")
                    text.append(f"{error}\n")
            details.update(text)
            return
        details.update(self._details_for(ref))

    def _details_for(self, ref: NodeRef) -> Text:
        text = Text()

        def row(label: str, value) -> None:
            text.append(f"{label:<12}", style="bold")
            text.append(value if isinstance(value, Text) else Text(str(value)))
            text.append("\n")

        if ref.kind == "folder":
            names = self.folder_scenarios.get(ref.key, [])
            row("folder", self._rel(ref.path))
            row("scenarios", len(names))
            bad = [n for n in names if self.status_of(n) in ("failed", "error", "blocked")]
            if bad:
                text.append("\nfailing\n", style="bold red")
                for name in bad:
                    text.append(f"  ✘ {name}\n", style="red")
            text.append("\nenter: run folder (twister -T)", style="bright_black")
            return text

        scenario = self.discovery.by_name().get(ref.scenario or "")
        if scenario is None:
            return Text("Scenario no longer exists.", style="bright_black")
        if ref.kind == "case":
            assert ref.case is not None
            row("case", ref.case.id)
            row("function", ref.case.func)
            row("source", f"{self._rel(ref.case.file)}:{ref.case.line}")
            row("scenario", scenario.name)
            for platform, result in self.store.for_scenario(scenario.name).items():
                status = result.cases.get(ref.case.id)
                icon, style = self._icon(status)
                row(platform, Text(f"{icon} {status or 'no result'}", style=style))
            text.append("\nenter: run only this case (native targets, via -test=)",
                        style="bright_black")
            return text

        row("scenario", scenario.name)
        row("yaml", self._rel(scenario.yaml_file))
        if scenario.tags:
            row("tags", ", ".join(scenario.tags))
        if scenario.platform_allow:
            row("allow", ", ".join(scenario.platform_allow))
        if scenario.integration_platforms:
            row("integration", ", ".join(scenario.integration_platforms))
        if scenario.harness:
            row("harness", scenario.harness)
        if scenario.build_only:
            row("build only", "yes")
        row("cases", f"{len(scenario.cases)} in {len(scenario.suites)} suites")
        results = self.store.for_scenario(scenario.name)
        if results:
            text.append("\nlast results\n", style="bold")
        for platform, result in results.items():
            icon, style = self._icon(result.status)
            line = Text(f"  {icon} {platform:<28} {result.status}", style=style)
            line.append(f"  build {result.build_time:.1f}s  run {result.execution_time:.2f}s",
                        style="bright_black")
            text.append(line)
            text.append("\n")
            if result.reason and result.status != "passed":
                text.append(f"    reason: {result.reason}\n", style="red")
            failed_cases = [c for c, s in result.cases.items() if s in ("failed", "error")]
            for case_id in failed_cases:
                text.append(f"    ✘ {case_id}\n", style="red")
            if result.log and result.status in ("failed", "error"):
                tail = result.log.strip().splitlines()[-40:]
                text.append("    ── log tail ──\n", style="bright_black")
                for log_line in tail:
                    text.append("    ")
                    text.append(Text.from_ansi(log_line))
                    text.append("\n")
        return text

    # -- job callbacks ----------------------------------------------------------

    def _on_job_change(self, job: Job) -> None:
        self._dirty = True

    def _on_job_line(self, job: Job, line: str) -> None:
        if job.id == self.viewed_job:
            self.query_one("#log", RichLog).write(Text.from_ansi(line))

    def _on_job_finished(self, job: Job) -> None:
        if job.results:
            self.store.merge(job.results, job.target.only_cases)
            try:
                self.store.save()
            except OSError as exc:
                self.notify(f"could not save results: {exc}", severity="error")
        self.recompute_live()
        if self.failed_only:
            self.rebuild_tree()
        self._dirty = True
        self.update_details()
        if job.state == "cancelled":
            return
        statuses = [r.status for r in job.results]
        passed = statuses.count("passed")
        failed = sum(statuses.count(s) for s in ("failed", "error", "blocked"))
        message = f"#{job.id} {job.target.title}: {passed} passed, {failed} failed"
        if job.state == "error":
            self.notify(f"#{job.id} could not start twister — see output", severity="error")
        elif failed or job.state == "failed":
            self.notify(message, severity="error", timeout=8)
            self.bell()
        else:
            self.notify(message, timeout=4)

    # -- running ------------------------------------------------------------------

    def submit(self, refs: list[NodeRef]) -> None:
        try:
            target = make_target(refs, self.discovery)
        except ValueError as exc:
            self.notify(str(exc), severity="warning")
            return
        self._submit_target(target)

    def _submit_target(self, target: RunTarget) -> None:
        options = RunOptions(
            platforms=list(self.options.platforms),
            integration=self.options.integration,
            inline_logs=self.options.inline_logs,
            verbose=self.options.verbose,
            extra_args=list(self.options.extra_args),
            jobs=self.options.jobs,
        )
        job = self.jobs.submit(target, options)
        if job is None:
            self.notify("already queued", severity="warning", timeout=2)
            return
        self.last_target = target
        self.show_job_log(job)
        self._dirty = True

    def _cursor_ref(self) -> NodeRef | None:
        node = self.tree.cursor_node
        return node.data if node is not None else None

    def action_run_cursor(self) -> None:
        ref = self._cursor_ref()
        if ref is not None:
            self.submit([ref])

    def action_toggle_mark(self) -> None:
        ref = self._cursor_ref()
        if ref is None:
            return
        if ref.key in self.marks:
            del self.marks[ref.key]
        else:
            self.marks[ref.key] = ref
        self.node_index[ref.key].set_label(self.label_for(ref))
        self.tree.action_cursor_down()
        self._update_mark_subtitle()

    def _update_mark_subtitle(self) -> None:
        panel = self.query_one("#tests-panel")
        panel.border_subtitle = f"{len(self.marks)} marked" if self.marks else ""

    def action_clear_marks(self) -> None:
        self.marks.clear()
        self.refresh_labels()
        self._update_mark_subtitle()

    def _marked_or_cursor(self) -> list[NodeRef]:
        if self.marks:
            return list(self.marks.values())
        ref = self._cursor_ref()
        return [ref] if ref else []

    def action_run_marked(self) -> None:
        refs = self._marked_or_cursor()
        if refs:
            self.submit(refs)
            self.action_clear_marks()

    def action_run_marked_parallel(self) -> None:
        refs = self._marked_or_cursor()
        for ref in refs:
            self.submit([ref])
        if refs:
            self.notify(f"queued {len(refs)} jobs, {self.jobs.max_parallel} in parallel",
                        timeout=3)
            self.action_clear_marks()

    def action_run_all(self) -> None:
        self.submit([NodeRef("folder", root) for root in self.discovery.roots])

    def action_rerun_failed(self) -> None:
        by_name = self.discovery.by_name()
        failed = [n for n in self.store.failed_scenarios() if n in by_name]
        if not failed:
            self.notify("no failed scenarios", timeout=2)
            return
        self.submit([NodeRef("scenario", by_name[n].directory, n) for n in failed])

    # -- jobs panel -----------------------------------------------------------------

    def _selected_job(self) -> Job | None:
        job_list = self.query_one(JobList)
        if job_list.highlighted is None:
            return None
        option = job_list.get_option_at_index(job_list.highlighted)
        return next((j for j in self.jobs.jobs if str(j.id) == option.id), None)

    @on(OptionList.OptionHighlighted, "#jobs")
    def _job_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        job = next((j for j in self.jobs.jobs if str(j.id) == event.option.id), None)
        if job is not None and job.id != self.viewed_job:
            self.show_job_log(job)

    def action_cancel_job(self) -> None:
        job = self._selected_job()
        if job is not None and job.active:
            self.jobs.cancel(job)

    def action_rerun_job(self) -> None:
        job = self._selected_job()
        if job is not None:
            self._submit_target(job.target)

    def action_clear_jobs(self) -> None:
        self.jobs.clear_finished()
        if self.viewed_job not in {j.id for j in self.jobs.jobs}:
            self.viewed_job = None
            self.show_job_log(None)
        self.refresh_jobs()

    def action_cancel_all(self) -> None:
        self.jobs.cancel_all()

    # -- settings --------------------------------------------------------------------

    def action_platforms(self) -> None:
        def apply(result: list[str] | None) -> None:
            if result is not None:
                self.options.platforms = result
                self.update_status()

        self.push_screen(PlatformScreen(self.discovery.platforms(), self.options.platforms), apply)

    def action_toggle_integration(self) -> None:
        self.options.integration = not self.options.integration
        self.update_status()

    def action_toggle_autorun(self) -> None:
        self.auto_run = not self.auto_run
        self.notify(f"auto-run on file change {'on' if self.auto_run else 'off'}", timeout=2)
        self.update_status()

    def action_parallel(self, delta: int) -> None:
        self.jobs.set_max_parallel(self.jobs.max_parallel + delta)
        self._dirty = True

    def action_filter(self) -> None:
        box = self.query_one("#filter", FilterInput)
        box.add_class("visible")
        box.focus()

    def action_clear_filter(self) -> None:
        box = self.query_one("#filter", FilterInput)
        box.value = ""
        box.remove_class("visible")
        self.tree.focus()

    @on(Input.Changed, "#filter")
    def _filter_changed(self, event: Input.Changed) -> None:
        self.filter_text = event.value.strip()
        self.rebuild_tree()

    @on(Input.Submitted, "#filter")
    def _filter_submitted(self, event: Input.Submitted) -> None:
        if not event.value.strip():
            event.input.remove_class("visible")
        self.tree.focus()

    def action_toggle_failed_only(self) -> None:
        self.failed_only = not self.failed_only
        self.rebuild_tree()
        self.query_one("#tests-panel").border_title = (
            "[1] Tests (failed only)" if self.failed_only else "[1] Tests"
        )

    async def action_rediscover(self) -> None:
        await self.rediscover()
        self.notify(f"{len(self.discovery.scenarios)} scenarios", timeout=2)

    def action_focus_panel(self, panel_id: str) -> None:
        self.query_one(f"#{panel_id}").focus()

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_edit(self) -> None:
        ref = self._cursor_ref()
        if ref is None or ref.kind == "folder":
            return
        if ref.kind == "case":
            assert ref.case is not None
            path, line = ref.case.file, ref.case.line
        else:
            scenario = self.discovery.by_name().get(ref.scenario or "")
            if scenario is None:
                return
            path, line = scenario.yaml_file, 1
        editor = shlex.split(os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi")
        try:
            with self.suspend():
                subprocess.run([*editor, f"+{line}", str(path)], check=False)
        except Exception as exc:  # SuspendNotSupported, missing editor, …
            self.notify(f"could not open editor: {exc}", severity="error")

    @on(Tree.NodeHighlighted, "#tests")
    def _node_highlighted(self) -> None:
        self.update_details()

    # -- file watching ------------------------------------------------------------

    @staticmethod
    def _watch_filter(_change, path: str) -> bool:
        parts = Path(path).parts
        if any(p in WATCH_IGNORE_PARTS or p.startswith("twister-out") for p in parts):
            return False
        return not path.endswith(WATCH_IGNORE_SUFFIXES)

    @work(exclusive=True, group="watch")
    async def watch_files(self) -> None:
        try:
            from watchfiles import awatch
        except ImportError:
            self.notify("watchfiles not installed — live reload disabled", severity="warning")
            return
        paths = [p for p in [*self.config.roots, *self.config.watch_paths] if p.exists()]
        if not paths:
            return
        async for changes in awatch(*paths, watch_filter=self._watch_filter, debounce=600):
            changed = [Path(p) for _, p in changes]
            await self.rediscover()
            if self.auto_run:
                self._auto_run(changed)

    def _auto_run(self, changed: list[Path]) -> None:
        affected = [
            s for s in self.discovery.scenarios
            if any(s.directory == p or s.directory in p.parents for p in changed)
        ]
        if affected:
            names = list(dict.fromkeys(s.name for s in affected))
            by_name = self.discovery.by_name()
            self.submit([NodeRef("scenario", by_name[n].directory, n) for n in names])
        elif self.last_target is not None:
            self._submit_target(self.last_target)

    async def on_unmount(self) -> None:
        self.jobs.shutdown()
