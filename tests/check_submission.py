"""Verify submission structure, complete case evidence and actual resource ledgers."""
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRIES = {"README.md", "requirements.txt", ".env.example", ".gitignore", "src", "tests", "examples", "data", "docs"}
DOCS = {"01-requirements.md", "02-solution.md", "03-evaluation.md", "04-ai-usage.md", "05-retrospective.md"}
LOCAL_ONLY = {".env", ".runtime", ".git", ".venv", "__pycache__"}
CASES = ["normal", "missing-budget", "missing-deadline", "tool-failure", "over-budget", "duplicate",
         "no-feasible", "deadline", "deadline-failure", "transient-failure", "save-failure", "resume-before", "resume",
         "live-normal", "live-over-budget", "live-transient-failure"]


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    root_entries = {p.name for p in ROOT.iterdir()} - LOCAL_ONLY
    assert root_entries == ENTRIES, "Unexpected or missing root files"
    assert {p.name for p in (ROOT / "docs").iterdir()} == DOCS, "Five required documents must be present"
    assert not list((ROOT / "examples").glob("*.py")), "Verification scripts belong in tests"
    for case in CASES:
        request, output, trace = [read(ROOT / f"examples/{case}.{kind}.json") for kind in ["input", "output", "trace"]]
        assert request["request_id"] == output["request_id"] == trace["request_id"], case
        assert trace["trace"] == output["trace"] and trace["source_output"] == case + ".output.json", case
        if output["status"] == "needs_information":
            assert output["mode"] == "validation" and output["total_cost"] == 0 and output["saved_plan"] is None
            continue
        assert output["mode"] == ("live" if case.startswith("live-") else "mock"), case
        assert sum(event["cost"] for event in output["tool_results"]) == output["total_cost"] <= output["budget"], case
        assert sum(event["minutes"] for event in output["tool_results"]) == output["elapsed_minutes"], case
        if output["status"] == "completed":
            assert output["saved_plan"] and output["saved_plan"]["total_cost"] == output["total_cost"], case
            assert datetime.fromisoformat(output["saved_plan"]["completed_at"]) <= datetime.fromisoformat(output["deadline"]), case
        if case == "over-budget":
            assert output["quotes"]["premium"]["projected_total"] == 12 and output["total_cost"] == 8
    duplicate, normal = [read(ROOT / f"examples/{name}.output.json") for name in ["duplicate", "normal"]]
    assert duplicate["duplicate"] and duplicate["tool_results"] == normal["tool_results"]
    assert duplicate["saved_plan"]["plan_id"] == normal["saved_plan"]["plan_id"]
    resume = read(ROOT / "examples/resume.output.json")
    assert resume["resumed"] and sum(x["action"] == "search_materials" for x in resume["tool_results"]) == 1
    offline = read(ROOT / "examples/offline-validation.json")
    assert offline["all_passed"] and offline["tests_run"] == 30 and offline["scenarios"] == 13
    assert (ROOT / "examples/test-results.txt").read_text(encoding="utf-8").rstrip().endswith("OK")
    live = read(ROOT / "examples/live-validation-summary.json")
    assert live["all_passed"] and len(live["checks"]) == 3
    pending_report = (ROOT / "examples/submission-check.json").resolve()
    for path in [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md")), ROOT / "examples/README.md"]:
        for target in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
            if target.startswith(("https:", "http:", "#")):
                continue
            resolved = (path.parent / target.split("#")[0]).resolve()
            assert resolved.exists() or resolved == pending_report, (str(path), target)
    result = {"checked_at": datetime.now(timezone(timedelta(hours=8))).isoformat(), "all_passed": True,
              "root_entries": sorted(root_entries), "documents": sorted(DOCS), "evidence_groups": len(CASES),
              "offline_runs": 13, "live_paths": 3, "unit_tests": 30, "trace_matches_actual_output": True,
              "resource_ledgers_consistent": True, "duplicate_no_extra_charges": True, "resume_preserves_success": True,
              "document_links_valid": True}
    pending_report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"submission": "passed", "evidence_groups": len(CASES), "tests": 30}))


if __name__ == "__main__":
    main()
