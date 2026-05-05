import json
from pathlib import Path


def load_json(path):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(data, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )