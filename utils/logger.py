from pathlib import Path
from utils.json_utils import save_json


class TaskLogger:
    def __init__(self, app_name):
        self.app_name = app_name
        self.records = []

    def add_step(self, step_index, page_info, decision, result):
        self.records.append({
            "step_index": step_index,
            "page_info": page_info,
            "decision": decision,
            "result": result
        })

    def save(self):
        out_path = Path("results/logs") / f"{self.app_name}.json"
        save_json(self.records, out_path)
        return str(out_path)