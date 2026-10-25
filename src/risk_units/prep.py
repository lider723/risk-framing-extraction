"""Unchanged historical paragraphing/chunking functions; tokenizer set explicitly by runner."""
from __future__ import annotations
import json
import math
import re
from pathlib import Path
TOKENIZER = None

def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def paragraph_map(article: dict) -> dict[str, str]:
    result = {"P000": article["title"]}
    for line in article["paragraph_numbered_article"].splitlines():
        match = re.match(r"^\[(P\d{3,})\]\s(.*)$", line)
        if not match or match[1] in result:
            raise ValueError(f"Invalid or repeated paragraph in {article['record_id']}: {line[:60]}")
        result[match[1]] = match[2]
    return result


def estimate_tokens(text: str) -> int:
    if TOKENIZER is not None:
        return len(TOKENIZER.encode(text))
    # Planning approximation, not an exact tokenizer or a billing measure.
    return math.ceil(len(text) / 4)


def paragraph_chunks(paragraphs: dict[str, str], budget: int = 800) -> list[list[str]]:
    ids = list(paragraphs)
    chunks: list[list[str]] = []
    start = 0
    while start < len(ids):
        end = start + 1
        # A long paragraph remains intact. Every next block overlaps one whole
        # paragraph and includes at least one new paragraph to make progress.
        if chunks and end < len(ids):
            end += 1
        while end < len(ids):
            text = "\n".join(f"[{pid}] {paragraphs[pid]}" for pid in ids[start:end + 1])
            if estimate_tokens(text) > budget:
                break
            end += 1
        chunks.append(ids[start:end])
        if end == len(ids):
            break
        start = end - 1 if end - start > 1 else end
    return chunks
