import csv
import json
from pathlib import Path
from typing import Any


class RunRecorder:
    def __init__(self, run_dir: str | Path) -> None:
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def append_jsonl(self, filename: str, record: dict[str, Any]) -> None:
        """Input: filename and JSON-serializable record. Output: none. Append one run event."""
        path = self.run_dir / filename
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    def read_jsonl(self, filename: str) -> list[dict[str, Any]]:
        """Input: filename. Output: list of records. Read a run JSONL artifact."""
        path = self.run_dir / filename
        if not path.exists():
            return []
        records: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                if line.strip():
                    records.append(json.loads(line))
        return records

    def seen_expression_hashes(self) -> set[str]:
        """Input: existing run records. Output: expression hashes. Support resume without duplicate simulations."""
        hashes: set[str] = set()
        for record in self.read_jsonl("all_alphas.jsonl"):
            expression_hash = record.get("expression_hash")
            if expression_hash:
                hashes.add(str(expression_hash))
        return hashes

    def write_candidates(self, rows: list[dict[str, Any]]) -> None:
        """Input: candidate rows. Output: candidates.csv. Persist hard-check-passing Alphas."""
        path = self.run_dir / "candidates.csv"
        fieldnames = ["alpha_id", "expression_hash", "sharpe", "fitness", "turnover", "returns", "warnings"]
        with path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    def write_markdown(self, filename: str, content: str) -> None:
        """Input: filename and markdown content. Output: markdown file. Save run summaries."""
        path = self.run_dir / filename
        path.write_text(content, encoding="utf-8")
