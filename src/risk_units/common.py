from __future__ import annotations
import re
from typing import Any

def validate(value: Any, schema: dict, path: str = "answer") -> list[str]:
    kind = schema["type"]
    expected = {"object": dict, "array": list, "string": str, "boolean": bool}[kind]
    if not isinstance(value, expected):
        return [f"{path}: expected {kind}"]
    errors = []
    if kind == "object":
        if set(value) != set(schema["required"]):
            errors.append(f"{path}: missing or extra fields")
        for key, child in schema["properties"].items():
            if key in value:
                errors.extend(validate(value[key], child, path + "." + key))
    elif kind == "array":
        for index, item in enumerate(value):
            errors.extend(validate(item, schema["items"], f"{path}[{index}]"))
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: illegal enum")
    return errors

def sentence_spans(text: str) -> list[tuple[int, int]]:
    """Deterministic same-paragraph boundaries; retain exact character slices."""
    starts = [0]
    abbreviations = ("Mr.", "Mrs.", "Ms.", "Dr.", "Prof.", "Jr.", "Sr.", "St.", "U.S.", "U.K.", "A.I.", "e.g.", "i.e.")
    for match in re.finditer(r"[.!?][\"'”’)]*\s+(?=[\"'“‘(]*[A-Z0-9])", text):
        prefix = text[:match.start() + 1]
        if prefix.endswith(abbreviations) or re.search(r"\b[A-Z]\.$", prefix):
            continue
        starts.append(match.end())
    return [(start, (starts[index + 1] if index + 1 < len(starts) else len(text))) for index, start in enumerate(starts)]

def candidate_context(candidate: dict, paragraphs: dict) -> dict:
    text = paragraphs.get(candidate["paragraph_id"], "")
    quote = candidate["quote"].strip()
    start = text.find(quote) if quote else -1
    if start < 0:
        return {"preceding": "", "following": "", "located": False, "target": candidate["quote"]}
    end = start + len(quote)
    spans = sentence_spans(text)
    preceding = [pair for pair in spans if pair[1] <= start]
    following = [pair for pair in spans if pair[0] >= end]
    prev = text[slice(*preceding[-1])].strip() if preceding else ""
    next_ = text[slice(*following[0])].strip() if following else ""
    return {"preceding": prev, "following": next_, "located": True, "target": candidate["quote"]}

def local_package(candidates: list[dict], paragraphs: dict) -> str:
    lines = []
    for candidate in candidates:
        context = candidate_context(candidate, paragraphs)
        lines.extend([
            f"--- {candidate['candidate_id']} ---",
            "Preceding: " + context["preceding"],
            f"Target [{candidate['paragraph_id']}]: {context['target']}",
            "Following: " + context["following"],
        ])
    return "\n".join(lines) if lines else "(no candidates)"
