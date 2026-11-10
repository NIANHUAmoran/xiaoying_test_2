import copy
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from src.agent import run
from src.models import MockModel
from src.store import Store
from src.tools import Tools

ROOT = Path(__file__).resolve().parents[1]


class ScriptModel:
    mode = "mock"
    name = "scripted-test-double"

    def __init__(self, actions):
        self.actions = iter(actions)

    def decide(self, context):
        return next(self.actions)


def choose(action, variant=None):
    return {"action": action, "arguments": {"variant": variant} if variant else {}, "basis": "test decision"}


class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / "tasks.sqlite3")
        self.store = Store(self.path)
        self.world = json.loads((ROOT / "data/world.json").read_text(encoding="utf-8"))
        self.request = {"request_id": "T01", "theme": "健康生活", "budget": 20,
                        "deadline": "2026-11-11T10:00:00+08:00"}

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def execute(self, model=None, max_steps=16):
        return run(self.request, self.world, self.store, model or MockModel(), max_steps)

    def test_normal_plan_cost_dependencies_and_persistence(self):
        result = self.execute()
        self.assertEqual((result["status"], result["selected_variant"], result["total_cost"], result["elapsed_minutes"]), ("completed", "premium", 12, 8))
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM plans").fetchone()[0], 1)
        self.assertEqual([x["action"] for x in result["trace"]], ["search_materials", "estimate_cost", "generate_script", "save_plan", "finish"])
        self.assertEqual(result["total_cost"], sum(x["cost"] for x in result["tool_results"]))
        self.assertEqual(result["saved_plan"]["total_cost"], 12)

    def test_observe_12_then_replan_to_8_within_budget_10(self):
        self.request["budget"] = 10
        result = self.execute()
        self.assertEqual(result["quotes"]["premium"]["projected_total"], 12)
        self.assertFalse(result["quotes"]["premium"]["feasible"])
        self.assertEqual((result["status"], result["total_cost"], result["selected_variant"]), ("completed", 8, "lean"))
        self.assertNotIn("generate_script:premium", result["steps"])

    def test_no_feasible_budget_reports_gap_without_spending(self):
        self.request["budget"] = 5
        result = self.execute()
        self.assertEqual((result["status"], result["reason"], result["total_cost"]), ("incomplete", "budget_exceeded", 0))
        self.assertEqual(result["unmet_constraints"]["budget_gap"], 1)
        self.assertIsNone(result["saved_plan"])

    def test_deadline_causes_faster_variant_selection(self):
        self.request["deadline"] = "2026-11-11T09:05:00+08:00"
        result = self.execute()
        self.assertFalse(result["quotes"]["premium"]["feasible"])
        self.assertEqual((result["status"], result["selected_variant"], result["elapsed_minutes"]), ("completed", "lean", 5))

    def test_no_feasible_deadline_reports_time_gap(self):
        self.request["deadline"] = "2026-11-11T09:03:00+08:00"
        result = self.execute()
        self.assertEqual((result["status"], result["reason"]), ("incomplete", "deadline_exceeded"))
        self.assertEqual(result["unmet_constraints"]["deadline_gap_minutes"], 1)
        self.assertEqual(result["total_cost"], 0)

    def test_deadline_before_start_does_not_run_paid_work(self):
        self.request["deadline"] = "2026-11-11T08:59:00+08:00"
        result = self.execute()
        self.assertEqual((result["status"], result["reason"], result["total_cost"]), ("incomplete", "deadline_exceeded", 0))
        self.assertGreater(result["unmet_constraints"]["deadline_gap_minutes"], 0)

    def test_missing_budget_and_deadline_are_not_invented(self):
        del self.request["budget"]
        del self.request["deadline"]
        result = self.execute(ScriptModel([]))
        self.assertEqual(result["status"], "needs_information")
        self.assertEqual(result["missing_fields"], ["budget", "deadline"])
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0], 0)

    def test_transient_failure_replans_and_preserves_successful_search(self):
        self.world["failures"] = [{"tool": "generate_script", "variant": "premium", "mode": "once"}]
        result = self.execute()
        self.assertEqual((result["status"], result["selected_variant"], result["total_cost"]), ("completed", "lean", 8))
        self.assertEqual(result["steps"]["generate_script:premium"]["status"], "failed")
        self.assertEqual(sum(x["action"] == "search_materials" for x in result["tool_results"]), 1)
        self.assertIn("search_materials", result["preserved_successful_steps"])
        self.assertEqual(result["elapsed_minutes"], 6)

    def test_all_generation_failures_do_not_become_successful(self):
        self.world["failures"] = [{"tool": "generate_script", "mode": "always"}]
        result = self.execute()
        self.assertEqual((result["status"], result["reason"], result["total_cost"]), ("incomplete", "tool_failure", 0))
        self.assertTrue(all(x["status"] == "failed" for k, x in result["steps"].items() if k.startswith("generate_script")))
        self.assertIsNone(result["saved_plan"])

    def test_save_failure_preserves_generated_script_and_real_charges(self):
        self.world["failures"] = [{"tool": "save_plan", "mode": "always"}]
        result = self.execute()
        self.assertEqual((result["status"], result["reason"], result["total_cost"]), ("incomplete", "tool_failure", 10))
        self.assertEqual(result["steps"]["generate_script:premium"]["status"], "succeeded")
        self.assertIsNone(result["saved_plan"])

    def test_resume_after_failure_reuses_prior_success_and_does_not_double_charge(self):
        self.world["failures"] = [{"tool": "generate_script", "variant": "premium", "mode": "once"}]
        script = ScriptModel([choose("search_materials"), choose("estimate_cost", "premium"), choose("generate_script", "premium"), choose("finish")])
        before = self.execute(script)
        self.assertEqual(before["reason"], "tool_failure")
        self.store.close()
        self.store = Store(self.path)
        after = self.execute()
        self.assertEqual((after["status"], after["resumed"], after["total_cost"]), ("completed", True, 12))
        self.assertEqual(sum(x["action"] == "search_materials" for x in after["tool_results"]), 1)
        self.assertEqual(after["steps"]["generate_script:premium"]["status"], "succeeded")
        self.assertEqual(sum(x["result"].get("error") == "injected_tool_failure" for x in after["tool_results"]), 1)

    def test_resume_save_after_environment_recovery_reuses_script(self):
        self.world["failures"] = [{"tool": "save_plan", "mode": "once"}]
        before = self.execute()
        self.assertEqual(before["total_cost"], 10)
        after = self.execute()
        self.assertEqual((after["status"], after["total_cost"]), ("completed", 12))
        self.assertEqual(sum(x["action"] == "generate_script" for x in after["tool_results"]), 1)

    def test_duplicate_finished_task_has_one_plan_and_no_new_events(self):
        before = self.execute()
        after = self.execute(ScriptModel([]))
        self.assertEqual(after["saved_plan"]["plan_id"], before["saved_plan"]["plan_id"])
        self.assertTrue(after["duplicate"])
        self.assertEqual(after["tool_results"], before["tool_results"])
        self.assertEqual(after["total_cost"], 12)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM plans").fetchone()[0], 1)

    def test_changed_request_or_catalog_is_not_silently_reused(self):
        self.execute()
        self.request["budget"] = 30
        with self.assertRaisesRegex(ValueError, "request_id"):
            self.execute()
        self.request["budget"] = 20
        self.world["variants"]["premium"]["cost"] = 100
        with self.assertRaisesRegex(ValueError, "目录"):
            self.execute()

    def test_tool_cannot_bypass_dependencies_or_budget(self):
        self.request["budget"] = 5
        model = ScriptModel([choose("save_plan", "premium"), choose("search_materials"),
                             choose("estimate_cost", "premium"), choose("generate_script", "premium"), choose("finish")])
        result = self.execute(model)
        self.assertEqual(result["trace"][0]["observation"]["error"], "search_dependency_missing")
        self.assertEqual(result["steps"]["generate_script:premium"]["result"]["error"], "resource_limit")
        self.assertEqual(result["total_cost"], 0)
        self.assertIsNone(result["saved_plan"])

    def test_repeated_successful_tool_calls_are_cached(self):
        self.store.register(self.request, self.world)
        tools = Tools(self.world, self.store, self.request["request_id"])
        tools.execute("search_materials", {})
        tools.execute("estimate_cost", {"variant": "premium"})
        tools.execute("generate_script", {"variant": "premium"})
        result = tools.execute("generate_script", {"variant": "premium"})
        self.assertTrue(result["cached"])
        self.assertEqual(self.store.get("T01")["spent"], 10)

    def test_expensive_success_is_not_refunded_when_switching_variant(self):
        model = ScriptModel([choose("search_materials"), choose("estimate_cost", "premium"), choose("generate_script", "premium"),
                             choose("estimate_cost", "lean"), choose("generate_script", "lean"), choose("save_plan", "lean"), choose("finish")])
        result = self.execute(model)
        self.assertEqual((result["status"], result["total_cost"]), ("completed", 18))
        self.assertIn("generate_script:premium", result["preserved_successful_steps"])

    def test_step_limit_and_premature_finish_are_incomplete(self):
        result = self.execute(max_steps=1)
        self.assertEqual((result["status"], result["reason"]), ("incomplete", "step_limit"))
        self.assertEqual(self.execute(ScriptModel([choose("finish")]))["status"], "incomplete")

    def test_limit_after_save_reports_written_plan_and_incomplete(self):
        result = self.execute(max_steps=4)
        self.assertEqual((result["status"], result["reason"], result["total_cost"]), ("incomplete", "step_limit", 12))
        self.assertIsNotNone(result["saved_plan"])

    def test_invalid_model_action_does_not_mutate_budget(self):
        bad = {"action": "change_budget", "arguments": {"budget": 1000}, "basis": "override"}
        result = self.execute(ScriptModel([bad]))
        self.assertEqual((result["status"], result["reason"], result["total_cost"]), ("incomplete", "model_error", 0))

    def test_sqlite_save_failure_rolls_back_only_save_and_preserves_prior_steps(self):
        self.store.db.execute("CREATE TRIGGER reject_plan BEFORE INSERT ON plans BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
        self.store.db.commit()
        result = self.execute()
        self.assertEqual((result["status"], result["reason"], result["total_cost"]), ("incomplete", "tool_failure", 10))
        self.assertEqual(result["steps"]["generate_script:premium"]["status"], "succeeded")
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM plans").fetchone()[0], 0)

    def test_concurrent_same_step_charges_once(self):
        self.store.register(self.request, self.world)
        tools = Tools(self.world, self.store, "T01")
        tools.execute("search_materials", {})
        tools.execute("estimate_cost", {"variant": "premium"})
        def generate(_):
            other = Store(self.path)
            try:
                return Tools(self.world, other, "T01").execute("generate_script", {"variant": "premium"})
            finally:
                other.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(generate, [0, 1]))
        self.assertEqual(sum(bool(x["cached"]) for x in results), 1)
        self.assertEqual(self.store.get("T01")["spent"], 10)

    def test_invalid_budget_and_timezone_are_rejected(self):
        for budget in [-1, 1.5, True, "10"]:
            self.request["budget"] = budget
            with self.assertRaises(ValueError):
                self.execute()
        self.request["budget"] = 20
        self.request["deadline"] = "2026-11-11T10:00:00"
        with self.assertRaises(ValueError):
            self.execute()

    def test_unmatched_materials_do_not_generate_script(self):
        self.request["theme"] = "not-in-catalog"
        result = self.execute()
        self.assertEqual(result["status"], "incomplete")
        self.assertIsNone(result["saved_plan"])

    def test_negative_tool_fee_is_not_a_budget_credit(self):
        self.world["variants"]["premium"]["cost"] = -10
        with self.assertRaises(ValueError):
            self.execute()

    def test_completed_plan_cannot_spend_more_or_change_persisted_result(self):
        model = ScriptModel([choose("search_materials"), choose("estimate_cost", "premium"), choose("generate_script", "premium"),
                             choose("save_plan", "premium"), choose("estimate_cost", "lean"), choose("generate_script", "lean"), choose("finish")])
        result = self.execute(model)
        self.assertEqual((result["status"], result["total_cost"], result["saved_plan"]["total_cost"]), ("completed", 12, 12))
        self.assertEqual(result["trace"][-2]["observation"]["error"], "task_already_completed")
