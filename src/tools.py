import json
from datetime import timedelta

from .domain import fingerprint, quote, timestamp


SCHEMAS = {"search_materials": set(), "estimate_cost": {"variant"},
           "generate_script": {"variant"}, "save_plan": {"variant"}, "finish": set()}


class Tools:
    def __init__(self, world, store, task_id):
        self.world, self.store, self.task_id = world, store, task_id

    def execute(self, action, arguments):
        return self.store.apply(self.task_id, lambda state: self._execute(state, action, arguments))

    def _execute(self, state, action, args):
        if action == "save_plan" and state["saved_plan"]:
            return {**state["saved_plan"], "cached": True}
        variant = args.get("variant")
        key = action + (":" + variant if variant else "")
        old = state["steps"].get(key)
        if old and old["status"] == "succeeded" and action != "estimate_cost":
            return {**old["result"], "cached": True}
        if state["saved_plan"]:
            return {"ok": False, "error": "task_already_completed", "charged": 0, "cached": True}
        if variant and variant not in self.world["variants"]:
            return self._record(state, key, action, args, {"ok": False, "error": "unknown_variant"})
        if action != "search_materials" and state["steps"].get("search_materials", {}).get("status") != "succeeded":
            return self._record(state, key, action, args, {"ok": False, "error": "search_dependency_missing"})
        if action in {"generate_script", "save_plan"}:
            if variant not in state["quotes"]:
                return self._record(state, key, action, args, {"ok": False, "error": "estimate_dependency_missing"})
            fresh = quote(state, self.world, variant)
            if not fresh["feasible"]:
                return self._record(state, key, action, args, {"ok": False, "error": "resource_limit", "estimate": fresh})
            if action == "save_plan" and state["steps"].get("generate_script:" + variant, {}).get("status") != "succeeded":
                return self._record(state, key, action, args, {"ok": False, "error": "script_dependency_missing"})
        if action == "estimate_cost":
            result = {"ok": True, **quote(state, self.world, variant)}
            state["quotes"][variant] = result
            state["selected_variant"] = variant
            return self._record(state, key, action, args, result)
        fee = self.world["variants"][variant] if action == "generate_script" else self.world["fees"][action]
        if state["spent"] + fee["cost"] > state["request"]["budget"] or timestamp(state["start_at"]) + timedelta(minutes=state["elapsed_minutes"] + fee["minutes"]) > timestamp(state["request"]["deadline"]):
            return self._record(state, key, action, args, {"ok": False, "error": "resource_limit"})
        failure = next((rule for rule in self.world.get("failures", [])
                        if rule["tool"] == action and rule.get("variant", "*") in {"*", variant}), None)
        attempts = sum(x["action"] == action and x["arguments"] == args for x in state["events"])
        if failure and (failure["mode"] == "always" or attempts == 0):
            minutes = failure.get("minutes", 1)
            state["elapsed_minutes"] += minutes
            return self._record(state, key, action, args,
                                {"ok": False, "error": "injected_tool_failure", "retryable": failure["mode"] == "once"}, minutes=minutes)
        if action == "search_materials":
            materials = [m for m in self.world["materials"] if state["request"]["theme"].lower() in " ".join(m["topics"]).lower()]
            if not materials:
                return self._record(state, key, action, args, {"ok": False, "error": "no_materials"})
            result = {"ok": True, "materials": materials}
        elif action == "generate_script":
            materials = state["steps"]["search_materials"]["result"]["materials"]
            result = {"ok": True, "variant": variant, "script_id": "script-" + fingerprint([self.task_id, variant])[:16],
                      "material_ids": [m["id"] for m in materials],
                      "script": f"主题：{state['request']['theme']}。开场展示 {materials[0]['title']}；讲解主题要点；结尾邀请观众参与。版本：{variant}。"}
        elif action == "save_plan":
            result = {"ok": True, "plan_id": "plan-" + fingerprint(self.task_id)[:20], "variant": variant,
                      "theme": state["request"]["theme"], "budget": state["request"]["budget"],
                      "deadline": state["request"]["deadline"], "script": state["steps"]["generate_script:" + variant]["result"],
                      "total_cost": state["spent"] + fee["cost"],
                      "completed_at": (timestamp(state["start_at"]) + timedelta(minutes=state["elapsed_minutes"] + fee["minutes"])).isoformat()}
            self.store.db.execute("INSERT INTO plans VALUES (?,?,?)", (self.task_id, result["plan_id"], json.dumps(result, ensure_ascii=False)))
            state["saved_plan"] = result
        else:
            raise ValueError("未知工具")
        state["spent"] += fee["cost"]
        state["elapsed_minutes"] += fee["minutes"]
        state["last_error"] = None
        return self._record(state, key, action, args, result, cost=fee["cost"], minutes=fee["minutes"])

    def _record(self, state, key, action, arguments, result, cost=0, minutes=0):
        event = {"action": action, "arguments": arguments, "result": result, "cost": cost, "minutes": minutes}
        state["events"].append(event)
        state["steps"][key] = {"status": "succeeded" if result["ok"] else "failed", "result": result}
        if not result["ok"]:
            state["last_error"] = {"action": action, "variant": arguments.get("variant"), "error": result["error"]}
        return {**result, "charged": cost, "elapsed_minutes": minutes, "cached": False}
