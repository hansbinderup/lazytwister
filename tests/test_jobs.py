import asyncio
import json
from pathlib import Path

from lazywest.discovery import discover
from lazywest.jobs import JobManager, NodeRef, RunOptions, build_command, make_target


def refs(found, *names):
    by_name = found.by_name()
    return [NodeRef("scenario", by_name[n].directory, n) for n in names]


def test_folder_target_uses_plain_testsuite_root(test_tree: Path):
    found = discover([test_tree])
    target = make_target([NodeRef("folder", test_tree / "lib")], found)
    assert target.testsuite_roots == [test_tree / "lib"]
    assert target.scenarios == [] and target.test_filters == []
    assert target.covered == {"lib.alpha.default", "lib.alpha.variant"}


def test_scenarios_and_folder_mix_expands_folder(test_tree: Path):
    found = discover([test_tree])
    target = make_target(
        refs(found, "drivers.beta") + [NodeRef("folder", test_tree / "lib")], found
    )
    assert target.scenarios == ["drivers.beta", "lib.alpha.default", "lib.alpha.variant"]
    assert target.test_filters == []


def test_single_case_target(test_tree: Path):
    found = discover([test_tree])
    scenario = found.by_name()["lib.alpha.default"]
    case = scenario.cases[1]
    target = make_target([NodeRef("case", scenario.directory, scenario.name, case)], found)
    assert target.scenarios == ["lib.alpha.default"]
    assert target.test_filters == ["alpha_suite::test_with_fixture"]
    assert target.only_cases == {"alpha_suite.with_fixture"}


def test_case_plus_scenario_uses_suite_wildcards(test_tree: Path):
    found = discover([test_tree])
    alpha = found.by_name()["lib.alpha.default"]
    target = make_target(
        [NodeRef("case", alpha.directory, alpha.name, alpha.cases[0])] + refs(found, "drivers.beta"),
        found,
    )
    assert target.test_filters == ["alpha_suite::test_adds", "beta_suite::*"]
    assert target.only_cases is None


def test_build_command(test_tree: Path, tmp_path: Path):
    found = discover([test_tree])
    alpha = found.by_name()["lib.alpha.default"]
    target = make_target([NodeRef("case", alpha.directory, alpha.name, alpha.cases[0])], found)
    cmd = build_command(["west", "twister"], target,
                        RunOptions(platforms=["native_sim"], extra_args=["-v"]), tmp_path, 4)
    assert cmd == [
        "west", "twister", "-T", str(alpha.directory), "-s", "lib.alpha.default",
        "-p", "native_sim", "-G", "-i", "-v", "-j", "4", "-O", str(tmp_path), "-v",
        "--", "-test=alpha_suite::test_adds",
    ]


async def test_parallel_jobs_use_separate_outdirs(test_tree, tmp_path, fake_twister, monkeypatch):
    monkeypatch.setenv("FAKE_DELAY", "0.3")
    monkeypatch.setenv("FAKE_FAIL", "drivers.beta")
    found = discover([test_tree])
    finished = []
    manager = JobManager(fake_twister, tmp_path / "state", tmp_path, max_parallel=2,
                         on_finished=finished.append)
    options = RunOptions()
    a = manager.submit(make_target(refs(found, "lib.alpha.default"), found), options)
    b = manager.submit(make_target(refs(found, "drivers.beta"), found), options)
    c = manager.submit(make_target(refs(found, "lib.alpha.variant"), found), options)
    assert manager.submit(make_target(refs(found, "lib.alpha.variant"), found), options) is None

    await asyncio.sleep(0.1)
    assert [j.state for j in (a, b, c)] == ["running", "running", "queued"]
    assert a.outdir != b.outdir

    for _ in range(100):
        if len(finished) == 3:
            break
        await asyncio.sleep(0.05)
    assert [j.state for j in (a, b, c)] == ["passed", "failed", "passed"]
    assert c.slot in (0, 1)  # slot reused, no third outdir
    assert b.live_status == {"drivers.beta": "failed"}
    assert b.results[0].status == "failed"
    argv = json.loads((b.outdir / "argv.json").read_text())
    assert "-s" in argv and "drivers.beta" in argv


async def test_cancel_running_job(test_tree, tmp_path, fake_twister, monkeypatch):
    monkeypatch.setenv("FAKE_DELAY", "10")
    found = discover([test_tree])
    finished = []
    manager = JobManager(fake_twister, tmp_path / "state", tmp_path, on_finished=finished.append)
    job = manager.submit(make_target(refs(found, "drivers.beta"), found), RunOptions())
    await asyncio.sleep(0.3)
    manager.cancel(job)
    for _ in range(100):
        if finished:
            break
        await asyncio.sleep(0.05)
    assert job.state == "cancelled"


async def test_missing_twister_reports_error(test_tree, tmp_path):
    found = discover([test_tree])
    finished = []
    manager = JobManager(["definitely-not-a-real-binary-xyz"], tmp_path, tmp_path,
                         on_finished=finished.append)
    job = manager.submit(make_target(refs(found, "drivers.beta"), found), RunOptions())
    await asyncio.sleep(0.2)
    assert job.state == "error"
    assert any("hint" in line for line in job.lines)


def test_parses_real_twister_lines():
    from lazywest.jobs import FAILURE_LINE_RE, RESULT_LINE_RE, ANSI_RE

    verbose = ("INFO    -  3/12 native_sim/native/64      libraries.encoding.json"
               "                            \x1b[32mPASSED\x1b[39m (native 0.004s <host>)")
    match = RESULT_LINE_RE.search(ANSI_RE.sub("", verbose))
    assert match and match.group(4) == "libraries.encoding.json" and match.group(5) == "PASSED"
    quiet = "ERROR   - native_sim/native/64      lib.x.native_sim   \x1b[31mFAILED\x1b[39m: Failed"
    match = FAILURE_LINE_RE.search(ANSI_RE.sub("", quiet))
    assert match and match.group(2) == "lib.x.native_sim"
