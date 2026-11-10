import os
from pathlib import Path


DEFAULT_ENV = Path(__file__).resolve().parents[1] / ".env"
ALLOWED = {"LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY"}


def load_env(path=DEFAULT_ENV):
    """Load three supported keys; shell environment takes precedence. Never log values."""
    path = Path(path)
    if not path.exists():
        return
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"模型配置文件第 {number} 行格式错误：需要 KEY=VALUE")
        key, value = (x.strip() for x in line.split("=", 1))
        if key not in ALLOWED:
            continue
        if value.startswith(("'", '"')):
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError(f"模型配置文件第 {number} 行引号未闭合")
            value = value[1:-1]
        os.environ.setdefault(key, value)
