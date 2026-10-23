import json
from pathlib import Path
from typing import Any

from wqb.principle_model import OptionCard, option_card_to_dict


OPTION_CARD_JSONL = "research_option_cards.jsonl"
OPTION_CARD_MARKDOWN = "research_option_cards.md"


# Input: OptionCard or option row and int; Output: str. Render one durable option card into review-friendly Markdown.
def _card_markdown(card: OptionCard | dict[str, Any], index: int) -> str:
    row = option_card_to_dict(card) if isinstance(card, OptionCard) else card
    evidence_rows = "\n".join(
        f"- `{item.get('path', '')}`: {item.get('title', '')}"
        for item in row["evidence"]
    )
    failure_rows = "\n".join(f"- {item}" for item in row["failure_modes"])
    secondary_incentives = ", ".join(row["secondary_incentives"]) or "none"
    return (
        f"## Option {index}: {row['title']}\n\n"
        f"- Primary Incentive: `{row['primary_incentive']}`\n"
        f"- Secondary Incentives: {secondary_incentives}\n"
        f"- Score: {row['score']['total']}\n\n"
        f"### Why Now\n{row['why_now']}\n\n"
        f"### Candidate Scope\n{row['candidate_scope']}\n\n"
        f"### Expected Asset Value\n{row['expected_asset_value']}\n\n"
        f"### Correlation Risk\n{row['correlation_risk']}\n\n"
        f"### Resource Cost\n{row['resource_cost']}\n\n"
        f"### Evidence\n{evidence_rows}\n\n"
        f"### Failure Modes\n{failure_rows}\n\n"
        f"### Decision Needed\n{row['decision_needed']}\n"
    )


# Input: output Path, option cards or rows, and timestamp str; Output: tuple[Path, Path]. Persist durable JSONL and Markdown option-card logs.
def write_option_cards(output_dir: Path, cards: list[OptionCard | dict[str, Any]], generated_at: str) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = output_dir / OPTION_CARD_JSONL
    markdown_path = output_dir / OPTION_CARD_MARKDOWN

    with jsonl_path.open("w", encoding="utf-8") as handle:
        for card in cards:
            row = option_card_to_dict(card) if isinstance(card, OptionCard) else dict(card)
            row["generated_at"] = generated_at
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    markdown_rows = [f"# Research Option Cards\n\nGenerated at: `{generated_at}`\n"]
    for index, card in enumerate(cards, start=1):
        markdown_rows.append(_card_markdown(card, index))
    markdown_path.write_text("\n\n".join(markdown_rows), encoding="utf-8")
    return jsonl_path, markdown_path
