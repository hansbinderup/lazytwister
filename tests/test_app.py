"""Smoke tests driving the TUI headlessly with Textual's pilot."""

import asyncio
from pathlib import Path

from lazytwister.app import AppConfig, LazyTwisterApp
from lazytwister.discovery import Workspace
from lazytwister.jobs import RunOptions


def make_app(test_tree: Path, tmp_path: Path, fake_twister) -> LazyTwisterApp:
    return LazyTwisterApp(AppConfig(
        cwd=tmp_path,
        roots=[test_tree],
        workspace=Workspace(None, None),
        twister_cmd=fake_twister,
        state_dir=tmp_path / "state",
        options=RunOptions(),
        max_parallel=2,
    ))


async def wait_for(predicate, timeout=5.0):
    for _ in range(int(timeout / 0.05)):
        if predicate():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("condition not met")


async def test_tree_shows_scenarios_and_runs_one(test_tree, tmp_path, fake_twister):
    app = make_app(test_tree, tmp_path, fake_twister)
    async with app.run_test(size=(160, 50)) as pilot:
        await wait_for(lambda: "s:drivers.beta" in app.node_index)
        assert "c:lib.alpha.default:alpha_suite.adds" in app.node_index
        app.tree.move_cursor(app.node_index["s:drivers.beta"])
        await pilot.press("enter")
        await wait_for(lambda: app.store.scenario_status("drivers.beta") == "passed")
        assert app.jobs.jobs[0].state == "passed"


async def test_mark_and_run_in_parallel(test_tree, tmp_path, fake_twister):
    app = make_app(test_tree, tmp_path, fake_twister)
    async with app.run_test(size=(160, 50)) as pilot:
        await wait_for(lambda: "s:drivers.beta" in app.node_index)
        app.tree.move_cursor(app.node_index["s:drivers.beta"])
        await pilot.press("space")
        app.tree.move_cursor(app.node_index["s:lib.alpha.default"])
        await pilot.press("space")
        assert len(app.marks) == 2
        await pilot.press("R")
        assert len(app.jobs.jobs) == 2
        await wait_for(lambda: all(not j.active for j in app.jobs.jobs))
        assert not app.marks


async def test_filter_narrows_tree(test_tree, tmp_path, fake_twister):
    app = make_app(test_tree, tmp_path, fake_twister)
    async with app.run_test(size=(160, 50)) as pilot:
        await wait_for(lambda: "s:drivers.beta" in app.node_index)
        await pilot.press("slash", *"beta")
        await pilot.pause()
        assert "s:drivers.beta" in app.node_index
        assert "s:lib.alpha.default" not in app.node_index
        await pilot.press("escape")
        await pilot.pause()
        assert "s:lib.alpha.default" in app.node_index


async def test_new_testcase_is_picked_up_live(test_tree, tmp_path, fake_twister):
    app = make_app(test_tree, tmp_path, fake_twister)
    async with app.run_test(size=(160, 50)):
        await wait_for(lambda: "s:drivers.beta" in app.node_index)
        new = test_tree / "subsys" / "gamma" / "testcase.yaml"
        new.parent.mkdir(parents=True)
        new.write_text("tests:\n  subsys.gamma: {}\n")
        await wait_for(lambda: "s:subsys.gamma" in app.node_index, timeout=10)


def test_pick_layout():
    pick = LazyTwisterApp.pick_layout
    assert pick(200, 50) == ("landscape", False)
    assert pick(160, 90) == ("portrait", False)   # tall window
    assert pick(100, 60) == ("portrait", False)   # narrow split
    assert pick(80, 30) == ("portrait", True)     # small
    assert pick(200, 20) == ("landscape", True)   # short
    assert pick(80, 30, "landscape") == ("landscape", True)


async def test_layout_adapts_to_resize(test_tree, tmp_path, fake_twister):
    app = make_app(test_tree, tmp_path, fake_twister)
    async with app.run_test(size=(200, 50)) as pilot:
        await wait_for(lambda: "s:drivers.beta" in app.node_index)
        screen = app.main_screen
        assert not screen.has_class("-portrait") and not screen.has_class("-compact")
        left, right = app.query_one("#left"), app.query_one("#right")
        assert left.region.y == right.region.y  # side by side

        await pilot.resize_terminal(100, 70)
        await pilot.pause()
        assert screen.has_class("-portrait") and not screen.has_class("-compact")
        assert left.region.x == right.region.x and right.region.y > left.region.y  # stacked

        await pilot.resize_terminal(80, 30)
        await pilot.pause()
        assert screen.has_class("-compact")
        assert not app.query_one("#details-panel").display
        await pilot.press("5")
        assert type(app.screen).__name__ == "InfoScreen"
        await pilot.press("escape")
        assert app.screen is screen

        await pilot.press("v")  # auto -> forced landscape
        await pilot.pause()
        assert app.layout_mode == "landscape" and not screen.has_class("-portrait")


async def test_zoom_maximizes_focused_panel(test_tree, tmp_path, fake_twister):
    app = make_app(test_tree, tmp_path, fake_twister)
    async with app.run_test(size=(200, 50)) as pilot:
        await wait_for(lambda: "s:drivers.beta" in app.node_index)
        await pilot.press("z")
        assert app.main_screen.maximized is app.query_one("#tests-panel")
        await pilot.press("z")
        assert app.main_screen.maximized is None
        await pilot.press("4", "z")
        assert app.main_screen.maximized is app.query_one("#log")
