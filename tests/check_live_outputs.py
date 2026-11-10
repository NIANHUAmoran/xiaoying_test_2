"""Compare genuine model outputs with their SQLite state and actual charge ledger."""
import argparse
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-dir", default=".runtime")
    parser.add_argument("--db-prefix", default="live-")
    args = parser.parse_args()
    rows = []
    for case in ["normal", "over-budget", "transient-failure"]:
        output = json.loads((ROOT / f"examples/live-{case}.output.json").read_text(encoding="utf-8"))
        assert output["mode"] == "live" and output["status"] == "completed"
        assert sum(x["cost"] for x in output["tool_results"]) == output["total_cost"] == output["saved_plan"]["total_cost"]
        assert sum(x["minutes"] for x in output["tool_results"]) == output["elapsed_minutes"]
        assert output["total_cost"] <= output["budget"]
        assert datetime.fromisoformat(output["saved_plan"]["completed_at"]) <= datetime.fromisoformat(output["deadline"])
        database = (Path(args.db_dir) / (args.db_prefix + case + ".sqlite3")).resolve()
        connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
        try:
            plans = connection.execute("SELECT body FROM plans WHERE task_id=?", (output["request_id"],)).fetchall()
            state = json.loads(connection.execute("SELECT state FROM tasks WHERE id=?", (output["request_id"],)).fetchone()[0])
        finally:
            connection.close()
        assert len(plans) == 1 and json.loads(plans[0][0]) == output["saved_plan"]
        assert state["events"] == output["tool_results"] and state["spent"] == output["total_cost"]
        if case == "over-budget":
            assert output["quotes"]["premium"]["projected_total"] == 12
            assert not output["quotes"]["premium"]["feasible"]
            assert output["selected_variant"] == "lean" and output["total_cost"] == 8
        errors = [step for step in output["trace"] if step.get("observation", {}).get("error") == "injected_tool_failure"]
        if case == "transient-failure":
            assert len(errors) == 1
            assert sum(x["action"] == "search_materials" for x in output["tool_results"]) == 1
        rows.append({"scenario": case, "model": output["model"], "status": output["status"],
                     "steps": len(output["trace"]), "total_cost": output["total_cost"],
                     "variant": output["selected_variant"], "elapsed_minutes": output["elapsed_minutes"],
                     "plan_count": len(plans), "database_consistent": True,
                     "observed_tool_failures": len(errors), "recovery_action": errors[0]["next_action"] if errors else None,
                     "actions": [{"action": x["action"], "arguments": x["arguments"]} for x in output["trace"]]})
    report = {"checked_at": datetime.now(timezone(timedelta(hours=8))).isoformat(), "all_passed": True,
              "checks": rows, "scope": "Three actual model runs; no claim of statistical reliability."}
    (ROOT / "examples/live-validation-summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"live_scenarios": len(rows), "database_checks": "passed"}))


if __name__ == "__main__":
    main()
