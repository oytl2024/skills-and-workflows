import json
from pathlib import Path

from wqb.principle_model import OptionCard, option_card_to_dict


OPTION_CARD_JSONL = "research_option_cards.jsonl"
OPTION_CARD_MARKDOWN = "research_option_cards.md"


# Input: OptionCard and int; Output: str; Purpose: render one option card into review-friendly markdown.
def _card_markdown(card: OptionCard, index: int) -> str:
    evidence_rows = "\n".join(f"- `{item.path}`: {item.title}" for item in card.evidence)
    failure_rows = "\n".join(f"- {item}" for item in card.failure_modes)
    secondary_incentives = ", ".join(card.secondary_incentives) or "none"
    return (
        f"## Option {index}: {card.title}\n\n"
        f"- Primary Incentive: `{card.primary_incentive}`\n"
        f"- Secondary Incentives: {secondary_incentives}\n"
        f"- Score: {card.score.total}\n\n"
        f"### Why Now\n{card.why_now}\n\n"
        f"### Candidate Scope\n{card.candidate_scope}\n\n"
        f"### Expected Asset Value\n{card.expected_asset_value}\n\n"
        f"### Correlation Risk\n{card.correlation_risk}\n\n"
        f"### Resource Cost\n{card.resource_cost}\n\n"
        f"### Evidence\n{evidence_rows}\n\n"
        f"### Failure Modes\n{failure_rows}\n\n"
        f"### Decision Needed\n{card.decision_needed}\n"
    )


# Input: output Path, list[OptionCard], and timestamp str; Output: tuple[Path, Path]; Purpose: persist durable JSONL and Markdown option-card logs.
def write_option_cards(output_dir: Path, cards: list[OptionCard], generated_at: str) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = output_dir / OPTION_CARD_JSONL
    markdown_path = output_dir / OPTION_CARD_MARKDOWN

    with jsonl_path.open("w", encoding="utf-8") as handle:
        for card in cards:
            row = option_card_to_dict(card)
            row["generated_at"] = generated_at
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    markdown_rows = [f"# Research Option Cards\n\nGenerated at: `{generated_at}`\n"]
    for index, card in enumerate(cards, start=1):
        markdown_rows.append(_card_markdown(card, index))
    markdown_path.write_text("\n\n".join(markdown_rows), encoding="utf-8")
    return jsonl_path, markdown_path
