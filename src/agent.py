from datetime import datetime, timezone
import sqlite3

from .domain import quote, validate, validate_world
from .models import ModelServiceError
from .tools import SCHEMAS, Tools


def validate_decision(decision):
    if not isinstance(decision, dict) or set(decision) != {"action", "arguments", "basis"}:
        raise ValueError("invalid_decision_fields")
    action = decision["action"]
    if action not in SCHEMAS or not isinstance(decision["arguments"], dict) or set(decision["arguments"]) != SCHEMAS[action]:
        raise ValueError("invalid_tool_or_arguments")
    if not isinstance(decision["basis"], str) or not 1 <= len(decision["basis"]) <= 500:
        raise ValueError("invalid_basis")
    if "variant" in decision["arguments"] and not isinstance(decision["arguments"]["variant"], str):
        raise ValueError("invalid_variant")


def run(request, world, store, model, max_steps=16):
    missing = validate(request)
    if type(max_steps) is not int or not 1 <= max_steps <= 100:
        raise ValueError("max_steps 必须为 1 到 100 的整数")
    if missing:
        return {"request_id": request["request_id"], "status": "needs_information", "missing_fields": missing,
                "reason": "missing_required_input", "task_plan": [], "steps": {}, "total_cost": 0,
                "saved_plan": None, "trace": [{"step": 1, "actor": "runtime", "action": "validate_input", "arguments": {},
                    "basis": "必填约束缺失，停止并请求补充", "observation": {"missing_fields": missing}, "next_action": None}],
                "model_calls": 0, "mode": "validation", "model": None,
                "generated_at": datetime.now(timezone.utc).isoformat()}
    validate_world(world)
    previous = store.db.execute("SELECT 1 FROM tasks WHERE id=?", (request["request_id"],)).fetchone()
    store.register(request, world)
    initial = store.get(request["request_id"])
    if initial["saved_plan"]:
        restored = [{"step": 1, "actor": "runtime", "action": "restore_completed_task", "arguments": {},
                     "basis": "同一请求已有保存结果，直接复用", "observation": {"cached": True, "plan_id": initial["saved_plan"]["plan_id"]},
                     "next_action": None}]
        return report(initial, world, model, restored, "already_completed", max_steps, resumed=True, duplicate=True)
    tools = Tools(world, store, request["request_id"])
    trace = []
    termination = "step_limit"
    for step in range(1, max_steps + 1):
        state = store.get(request["request_id"])
        context = {"request": request, "catalog": world["variants"], "save_fee": world["fees"]["save_plan"],
                   "state": {k: v for k, v in state.items() if k != "events"},
                   "resumed": bool(previous), "remaining_steps": max_steps - step + 1}
        decision = None
        try:
            decision = model.decide(context)
            validate_decision(decision)
        except Exception as exc:
            error = {"step": step, "error": "model_error", "detail": type(exc).__name__}
            if isinstance(exc, ModelServiceError):
                error["service_error"] = str(exc)
            if isinstance(decision, dict):
                error["response_fields"] = list(decision)
                error["returned_action"] = str(decision.get("action", ""))[:64]
            trace.append(error)
            termination = "model_error"
            break
        entry = {"step": step, "actor": "model", **decision}
        if decision["action"] == "finish":
            entry["observation"] = {"finished": True}
            trace.append(entry)
            termination = "finished"
            break
        try:
            result = tools.execute(decision["action"], decision["arguments"])
        except sqlite3.Error:
            result = {"ok": False, "error": "storage_error", "charged": 0}
            entry["observation"] = result
            trace.append(entry)
            termination = "tool_error"
            break
        entry["observation"] = result
        trace.append(entry)
    for index, entry in enumerate(trace):
        entry["next_action"] = trace[index + 1].get("action", "model_error") if index + 1 < len(trace) else None
    return report(store.get(request["request_id"]), world, model, trace, termination, max_steps, bool(previous))


def report(state, world, model, trace, termination, max_steps, resumed=False, duplicate=False):
    saved = state["saved_plan"]
    complete = saved is not None and termination in {"finished", "already_completed"}
    estimates = [quote(state, world, name) for name in world["variants"]] if not saved else []
    unmet = min(estimates, key=lambda x: (x["budget_gap"], x["deadline_gap_minutes"])) if estimates and not any(x["feasible"] for x in estimates) else None
    reason = None if complete else "step_limit" if termination == "step_limit" else "model_error" if termination == "model_error" else \
        "budget_exceeded" if unmet and unmet["budget_gap"] else "deadline_exceeded" if unmet and unmet["deadline_gap_minutes"] else \
        "tool_failure" if state["last_error"] or termination == "tool_error" else "finished_without_saved_plan"
    selected = saved["variant"] if saved else state["selected_variant"]
    keys = ["search_materials", "estimate_cost:" + selected, "generate_script:" + selected, "save_plan:" + selected] if selected else ["search_materials"]
    plan = [{"step": key, "depends_on": [keys[index - 1]] if index else [],
             "status": state["steps"].get(key, {}).get("status", "not_started")} for index, key in enumerate(keys)]
    return {"request_id": state["request"]["request_id"], "status": "completed" if complete else "incomplete",
            "reason": reason, "missing_fields": [], "mode": model.mode, "model": model.name,
            "generated_at": datetime.now(timezone.utc).isoformat(), "max_steps": max_steps,
            "termination": termination, "resumed": resumed, "duplicate": duplicate,
            "task_plan": plan, "steps": state["steps"], "quotes": state["quotes"],
            "tool_results": state["events"], "total_cost": state["spent"], "budget": state["request"]["budget"],
            "elapsed_minutes": state["elapsed_minutes"], "deadline": state["request"]["deadline"],
            "selected_variant": selected, "saved_plan": saved, "unmet_constraints": unmet,
            "preserved_successful_steps": [key for key, value in state["steps"].items() if value["status"] == "succeeded"],
            "model_calls": sum(entry.get("actor", "model") == "model" for entry in trace), "trace": trace}
