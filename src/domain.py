import hashlib
import json
import math
from datetime import datetime, timedelta


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("时间必须为带时区的 ISO 字符串")
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError("时间必须为带时区的 ISO 字符串") from None
    if result.tzinfo is None:
        raise ValueError("时间必须包含时区偏移")
    return result


def validate(request):
    if not isinstance(request, dict) or not isinstance(request.get("request_id"), str) or not request["request_id"].strip():
        raise ValueError("request_id 必须是非空字符串")
    missing = [key for key in ["theme", "budget", "deadline"] if key not in request or request[key] is None or request[key] == ""]
    if "theme" not in missing and (not isinstance(request["theme"], str) or not request["theme"].strip()):
        raise ValueError("theme 必须是非空字符串")
    if "budget" not in missing and (type(request["budget"]) is not int or request["budget"] < 0):
        raise ValueError("budget 必须为非负整数模拟单位")
    if "deadline" not in missing:
        timestamp(request["deadline"])
    if "start_at" in request:
        timestamp(request["start_at"])
    return missing


def initial_state(request, world):
    return {"request": request, "start_at": request.get("start_at", world["simulation_start"]),
            "spent": 0, "elapsed_minutes": 0, "steps": {}, "quotes": {}, "events": [],
            "selected_variant": None, "saved_plan": None, "last_error": None}


def validate_world(world):
    timestamp(world["simulation_start"])
    if not world["variants"]:
        raise ValueError("至少需要一个候选方案")
    for spec in list(world["variants"].values()) + list(world["fees"].values()):
        if any(type(spec.get(key)) is not int or spec[key] < 0 for key in ["cost", "minutes"]):
            raise ValueError("工具费用与耗时必须是非负整数")
    for failure in world.get("failures", []):
        if failure.get("mode") not in {"once", "always"} or type(failure.get("minutes", 1)) is not int or failure.get("minutes", 1) < 0:
            raise ValueError("故障配置非法")


def quote(state, world, variant):
    spec = world["variants"][variant]
    generated = state["steps"].get("generate_script:" + variant, {}).get("status") == "succeeded"
    searched = state["steps"].get("search_materials", {}).get("status") == "succeeded"
    save_done = state["saved_plan"] is not None
    cost = (0 if generated else spec["cost"]) + (0 if save_done else world["fees"]["save_plan"]["cost"])
    minutes = (0 if generated else spec["minutes"]) + (0 if save_done else world["fees"]["save_plan"]["minutes"])
    if not searched:
        cost += world["fees"]["search_materials"]["cost"]
        minutes += world["fees"]["search_materials"]["minutes"]
    total = state["spent"] + cost
    finish = timestamp(state["start_at"]) + timedelta(minutes=state["elapsed_minutes"] + minutes)
    deadline = timestamp(state["request"]["deadline"])
    budget_gap = max(0, total - state["request"]["budget"])
    time_gap = max(0, math.ceil((finish - deadline).total_seconds() / 60))
    return {"variant": variant, "projected_total": total, "spent_so_far": state["spent"],
            "remaining_cost": cost, "projected_finish": finish.isoformat(),
            "remaining_minutes": minutes, "budget_gap": budget_gap, "deadline_gap_minutes": time_gap,
            "feasible": budget_gap == 0 and time_gap == 0}
