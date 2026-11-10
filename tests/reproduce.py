"""Reproduce offline cases through the actual CLI, then run the unit tests."""
import copy
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"


def write(relative, value):
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def extract_traces():
    for path in sorted((ROOT / "examples").glob("*.output.json")):
        output = json.loads(path.read_text(encoding="utf-8"))
        write("examples/" + path.name.replace(".output.json", ".trace.json"),
              {"source_output": path.name, **{key: output.get(key) for key in ["request_id", "mode", "model", "generated_at", "trace"]}})


def main():
    started = time.monotonic()
    world = json.loads((ROOT / "data/world.json").read_text(encoding="utf-8"))
    once = copy.deepcopy(world)
    once["failures"] = [{"tool": "generate_script", "variant": "premium", "mode": "once", "minutes": 1}]
    failed = copy.deepcopy(world)
    failed["failures"] = [{"tool": "generate_script", "mode": "always", "minutes": 1}]
    save_failed = copy.deepcopy(world)
    save_failed["failures"] = [{"tool": "save_plan", "mode": "always", "minutes": 1}]
    for name, fixture in [("transient-failure", once), ("tool-failure", failed), ("save-failure", save_failed)]:
        write(f"data/{name}.world.json", fixture)
    base = {"theme": "健康生活", "budget": 20, "deadline": "2026-11-11T10:00:00+08:00"}
    cases = [
        ("normal", {}, [], "world", "completed"),
        ("missing-budget", {}, ["budget"], "world", "needs_information"),
        ("missing-deadline", {}, ["deadline"], "world", "needs_information"),
        ("over-budget", {"budget": 10}, [], "world", "completed"),
        ("no-feasible", {"budget": 5}, [], "world", "incomplete"),
        ("deadline", {"deadline": "2026-11-11T09:05:00+08:00"}, [], "world", "completed"),
        ("deadline-failure", {"deadline": "2026-11-11T09:03:00+08:00"}, [], "world", "incomplete"),
        ("tool-failure", {}, [], "tool-failure", "incomplete"),
        ("transient-failure", {}, [], "transient-failure", "completed"),
        ("save-failure", {}, [], "save-failure", "incomplete"),
    ]
    summary = []
    def execute(name, request, data, database, expected, max_steps=16):
        write(f"examples/{name}.input.json", request)
        argv = [sys.executable, "-B", "-m", "src", "--mock", "--input", f"examples/{name}.input.json",
                "--data", f"data/{data}.json" if data == "world" else f"data/{data}.world.json",
                "--db", str(database), "--output", f"examples/{name}.output.json", "--max-steps", str(max_steps)]
        process = subprocess.run(argv, cwd=ROOT, capture_output=True)
        expected_code = 1 if expected == "incomplete" else 0
        if process.returncode != expected_code:
            raise RuntimeError(f"{name}: unexpected exit {process.returncode}")
        output = json.loads((ROOT / f"examples/{name}.output.json").read_text(encoding="utf-8"))
        assert output["status"] == expected, (name, output["status"])
        summary.append({"scenario": name, "status": output["status"], "reason": output.get("reason"),
                        "exit_code": process.returncode, "total_cost": output["total_cost"], "mode": output["mode"]})
        return output
    with tempfile.TemporaryDirectory() as directory:
        temp = Path(directory)
        for name, changes, missing, data, expected in cases:
            request = {"request_id": "test2-" + name, **base, **changes}
            for field in missing:
                request.pop(field)
            output = execute(name, request, data, temp / (name + ".sqlite3"), expected)
            if name == "normal":
                repeated = execute("duplicate", request, "world", temp / "normal.sqlite3", "completed")
                assert repeated["duplicate"] and repeated["saved_plan"]["plan_id"] == output["saved_plan"]["plan_id"]
                assert repeated["tool_results"] == output["tool_results"] and repeated["total_cost"] == 12
            if name == "over-budget":
                assert output["quotes"]["premium"]["projected_total"] == 12 and output["total_cost"] == 8
        request = {"request_id": "test2-resume", **base}
        before = execute("resume-before", request, "transient-failure", temp / "resume.sqlite3", "incomplete", max_steps=3)
        after = execute("resume", request, "transient-failure", temp / "resume.sqlite3", "completed")
        assert before["steps"]["generate_script:premium"]["status"] == "failed"
        assert after["resumed"] and after["total_cost"] == 12
        assert sum(x["action"] == "search_materials" for x in after["tool_results"]) == 1
    # Live inputs are separate artifacts and always originate from their actual offline counterpart.
    for name in ["normal", "over-budget", "transient-failure"]:
        request = json.loads((ROOT / f"examples/{name}.input.json").read_text(encoding="utf-8"))
        request["request_id"] = "test2-live-" + name
        write(f"examples/live-{name}.input.json", request)
    extract_traces()
    write("examples/run-summary.json", summary)
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    with (ROOT / "examples/test-results.txt").open("w", encoding="utf-8") as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    write("examples/offline-validation.json", {"checked_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
          "tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
          "scenarios": len(summary), "elapsed_seconds": round(time.monotonic() - started, 2),
          "live_calls_performed": False, "all_passed": result.wasSuccessful()})
    print(json.dumps({"offline_scenarios": len(summary), "tests": result.testsRun, "passed": result.wasSuccessful()}))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
