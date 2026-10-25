from __future__ import annotations
from copy import deepcopy
import re
from . import common as legacy

def render(template, **values):
    for key, value in values.items():
        template = template.replace("{" + key + "}", str(value))
    known = ("record_id", "title", "paragraph_numbered_article", "list of C01..C_n quotes",
             "context_review_status", "candidate_context_package", "additional_context_package")
    if any("{" + key + "}" in template for key in known):
        raise ValueError("Unfilled prompt placeholder")
    return template

def canonical(text):
    """Normalization ONLY to find a unique original contiguous character slice."""
    output, starts, ends = [], [], []
    replacements = {"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"'}
    for index, character in enumerate(text):
        value = " " if character.isspace() else replacements.get(character, character).lower()
        if value == " " and output and output[-1] == " ":
            ends[-1] = index + 1
            continue
        for part in value:
            output.append(part); starts.append(index); ends.append(index + 1)
    return "".join(output), starts, ends

def original_slice(quote, paragraph):
    if quote and quote in paragraph:
        return quote, False
    normalized, starts, ends = canonical(paragraph)
    target = canonical(quote)[0].strip()
    if not target:
        return None, False
    places = [m.start() for m in re.finditer(re.escape(target), normalized)]
    if len(places) != 1:
        return None, False
    start = places[0]
    return paragraph[starts[start]:ends[start + len(target) - 1]], True

def restore_quotes(value, paragraphs):
    answer = deepcopy(value)
    repairs, checks = [], []

    def visit(item, path):
        if isinstance(item, dict):
            if "paragraph_id" in item and "quote" in item:
                pid, quote = item["paragraph_id"], item["quote"]
                raw_ok = bool(quote) and pid in paragraphs and quote in paragraphs[pid]
                checks.append({"path": path, "paragraph_id": pid, "raw_verbatim": raw_ok})
                if not raw_ok and pid in paragraphs:
                    restored, changed = original_slice(quote, paragraphs[pid])
                    if changed:
                        item["quote"] = restored
                        repairs.append({"path": path, "paragraph_id": pid, "before": quote,
                                        "after": restored, "method": "unique_original_contiguous_slice"})
            else:
                for key, child in item.items():
                    visit(child, path + "." + key)
        elif isinstance(item, list):
            for index, child in enumerate(item):
                visit(child, path + f"[{index}]")
    visit(answer, "answer")
    return answer, repairs, checks

def candidate_errors(answer, supplied):
    errors = []
    for i, candidate in enumerate(answer["candidates"]):
        pid, quote = candidate["paragraph_id"], candidate["quote"]
        if not quote or pid not in supplied or quote not in supplied[pid]:
            errors.append(f"candidates[{i}]: quote not in supplied original paragraph {pid}")
    return errors

def merge_candidates(existing, additions, paragraphs, origin):
    merged = deepcopy(existing)
    index = {(c["paragraph_id"], c["quote"]): c for c in merged}
    for candidate in additions:
        key = (candidate["paragraph_id"], candidate["quote"])
        occurrence = {"stage": origin, "original_candidate_id": candidate["candidate_id"]}
        if key not in index:
            item = {k: candidate[k] for k in ("paragraph_id", "quote", "proposition")}
            item["origins"] = []
            merged.append(item); index[key] = item
        index[key]["origins"].append(occurrence)
    # IDs used during discovery are append-only. Freeze article-order IDs once
    # both passes finish, not between confirmation rounds.
    for number, candidate in enumerate(merged, 1):
        candidate["candidate_id"] = f"C{number:02d}"
    return merged

def freeze_candidates(candidates, paragraphs):
    order = {pid: i for i, pid in enumerate(paragraphs)}
    result = sorted(deepcopy(candidates), key=lambda c: (order[c["paragraph_id"]], paragraphs[c["paragraph_id"]].find(c["quote"])))
    for number, candidate in enumerate(result, 1):
        candidate["candidate_id"] = f"C{number:02d}"
    return result

class ContextController:
    def __init__(self, paragraphs, candidates):
        self.paragraphs = paragraphs
        self.candidates = candidates
        self.full_paragraphs = set()
        self.review_completed = False
        self.events = []

    @property
    def status(self):
        return "complete" if self.review_completed else "pending"

    def additional(self):
        return "\n".join(f"[{pid}] {text}" for pid, text in self.paragraphs.items()
                         if pid in self.full_paragraphs) or "(none supplied)"

    def allowed(self):
        result = {pid: [self.paragraphs[pid]] for pid in self.full_paragraphs}
        for candidate in self.candidates:
            pid = candidate["paragraph_id"]
            context = legacy.candidate_context(candidate, self.paragraphs)
            text = self.paragraphs[pid]
            fragments = [context[name] for name in ("preceding", "target", "following") if context[name]]
            bounds = [(text.find(fragment), text.find(fragment) + len(fragment)) for fragment in fragments]
            if bounds and all(start >= 0 for start, _ in bounds):
                # They are adjacent original sentences, so the envelope only
                # restores original intervening whitespace, never unseen prose.
                result.setdefault(pid, []).append(text[min(x[0] for x in bounds):max(x[1] for x in bounds)])
        return result

    def snapshot(self):
        return {"context_review_status": self.status,
                "provided_full_paragraph_ids": [p for p in self.paragraphs if p in self.full_paragraphs],
                "full_article_supplied": set(self.paragraphs) == self.full_paragraphs,
                "article_review_previously_completed": self.review_completed,
                "allowed_original_intervals": self.allowed()}

    def accept_review_round(self, round_number):
        if self.full_paragraphs == set(self.paragraphs):
            self.review_completed = True
            self.events.append({"round": round_number, "event": "whole_article_confirmation_round_completed",
                                "paragraph_ids": list(self.paragraphs)})

    def expand(self, requests, round_number):
        before = set(self.full_paragraphs)
        ids = list(self.paragraphs)
        by_candidate = {c["candidate_id"]: c for c in self.candidates}
        for request in requests:
            if request["scope"] == "article":
                self.full_paragraphs.update(ids)
            else:
                for cid in request["source_candidates"]:
                    position = ids.index(by_candidate[cid]["paragraph_id"])
                    self.full_paragraphs.update(ids[max(0, position - 1):position + 2])
        if self.full_paragraphs == before:
            # An empty request list or repeated local request is not evidence
            # that article-wide qualifications have been checked.
            self.full_paragraphs.update(ids)
            reason = "controller_enforced_whole_article_review"
        else:
            reason = "model_context_requests"
        self.events.append({"round": round_number, "event": reason, "requests": requests,
                            "new_paragraph_ids": [p for p in ids if p in self.full_paragraphs - before]})

def confirmation_errors(answer, paragraphs, candidates, allowed):
    errors = []
    cids = {c["candidate_id"] for c in candidates}
    unit_map = {u["unit_id"]: u for u in answer["units"]}
    if len(unit_map) != len(answer["units"]):
        errors.append("duplicate unit_id")
    decisions = answer["candidate_decisions"]
    if {d["candidate_id"] for d in decisions} != cids:
        errors.append("candidate decisions must cover exactly every supplied candidate")
    for decision in decisions:
        cid, selected = decision["candidate_id"], decision["unit_ids"]
        if not decision["proposition"].strip() or not decision["reason"].strip():
            errors.append("empty decision proposition/reason")
        if decision["decision"] != "confirmed" and selected:
            errors.append("rejected/unresolved decision must have no unit_ids")
        if decision["decision"] == "confirmed" and not selected:
            errors.append("confirmed decision needs supporting units")
        for uid in selected:
            if uid not in unit_map or cid not in unit_map[uid]["source_candidates"]:
                errors.append(f"inconsistent candidate/unit mapping {cid}/{uid}")
    for unit in answer["units"]:
        uid = unit["unit_id"]
        sources = unit["source_candidates"]
        if not sources or not set(sources) <= cids or len(set(sources)) != len(sources):
            errors.append(f"{uid}: invalid source candidates")
        for cid in sources:
            if not any(d["candidate_id"] == cid and d["decision"] == "confirmed" and uid in d["unit_ids"] for d in decisions):
                errors.append(f"{uid}: candidate mapping lacks confirmed reverse decision")
        justification = unit["justification"]
        connection = justification["ai_connection"]
        if not justification["consequence"].strip() or not connection["relation"].strip() or justification["is_affirmative"] is not True:
            errors.append(f"{uid}: incomplete affirmative justification")
        if not unit["risk_claim_spans"] or not connection["evidence_spans"]:
            errors.append(f"{uid}: missing core/connection evidence")
        seen = set()
        for field in ("risk_claim_spans", "necessary_context_spans"):
            for span in unit[field]:
                key = (span["paragraph_id"], span["quote"])
                if key in seen:
                    errors.append(f"{uid}: duplicate core/context quote")
                seen.add(key)
        for span in connection["evidence_spans"]:
            if not any(span["paragraph_id"] == core["paragraph_id"] and span["quote"] in core["quote"] for core in unit["risk_claim_spans"]):
                errors.append(f"{uid}: connection evidence not contained in core evidence")
        for span in unit["risk_claim_spans"] + unit["necessary_context_spans"] + connection["evidence_spans"]:
            pid, quote = span["paragraph_id"], span["quote"]
            if not quote or pid not in paragraphs or quote not in paragraphs[pid]:
                errors.append(f"{uid}/{pid}: evidence not verbatim")
            elif not any(quote in fragment for fragment in allowed.get(pid, [])):
                errors.append(f"{uid}/{pid}: evidence not in actually supplied original intervals")
    for request in answer["context_requests"]:
        if not set(request["source_candidates"]) <= cids or not request["missing_information"].strip():
            errors.append("invalid context request candidates/information")
        if request["scope"] == "paragraph_and_neighbors" and not request["source_candidates"]:
            errors.append("neighbor request needs an anchor candidate")
    return errors

def final_projection(answer):
    return {"record_id": answer["record_id"], "risk_units": [
        {"unit_id": f"U{i:02d}", "risk_claim_spans": deepcopy(unit["risk_claim_spans"]),
         "necessary_context_spans": deepcopy(unit["necessary_context_spans"])}
        for i, unit in enumerate(answer["units"], 1)]}
