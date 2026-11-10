import argparse
import json
import sqlite3
import sys
from pathlib import Path

from .agent import run
from .config import DEFAULT_ENV, load_env
from .domain import validate
from .models import HTTPModel, MockModel
from .store import Store


def main():
    parser = argparse.ArgumentParser(description="内容任务规划 Agent：预算、截止时间、失败恢复与方案保存")
    parser.add_argument("--input", required=True)
    parser.add_argument("--data", default="data/world.json")
    parser.add_argument("--db", default=".runtime/tasks.sqlite3")
    parser.add_argument("--output")
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV))
    parser.add_argument("--max-steps", type=int, default=16)
    args = parser.parse_args()
    store = None
    try:
        request = json.loads(Path(args.input).read_text(encoding="utf-8-sig"))
        world = json.loads(Path(args.data).read_text(encoding="utf-8-sig"))
        missing = validate(request)
        if not args.mock and not missing:
            load_env(args.env_file)
        model = MockModel() if args.mock or missing else HTTPModel()
        Path(args.db).parent.mkdir(parents=True, exist_ok=True)
        store = Store(args.db)
        result = run(request, world, store, model, args.max_steps)
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text + "\n", encoding="utf-8")
        print(text)
        return 1 if result["status"] == "incomplete" else 0
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error) as exc:
        print(json.dumps({"error": type(exc).__name__, "detail": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    finally:
        if store:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
