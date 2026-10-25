"""Historical v5 execution bodies; ENV-only key adapter, November model default.

No client is constructed by importing this module. See docs/TECHNICAL_GUIDE.md.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time
from . import prep, common as legacy
from .contracts import (render, restore_quotes, candidate_errors, merge_candidates,
                        freeze_candidates, ContextController, confirmation_errors, final_projection)
MODEL = "gpt-4o-2024-11-20"
ENDPOINT = "https://api.vveai.com/v1"

def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


class StopRun(RuntimeError):
    pass


class Client:
    def __init__(self, output, schemas, max_calls=800, pause=1.0, retry_errors=False):
        from openai import OpenAI
        key = os.environ.get("OPENAI_API_KEY") or os.environ.get("LOCAL_FRAME_API_KEY")
        if not key:
            raise StopRun("Empty API key")
        self.secret = key
        self.sdk = OpenAI(api_key=key, base_url=ENDPOINT, timeout=120.0, max_retries=0)
        self.output, self.schemas, self.max_calls, self.pause = output, schemas, max_calls, pause
        self.retry_errors = retry_errors
        self.calls = 0
        self.last_call = 0.0
        self.consecutive_network_failures = 0
        self.state_path = output / "runtime_state.json"
        self.state = load(self.state_path) if self.state_path.exists() else {"attempted_calls": 0}

    def stage(self, relative, messages, kind, record_id):
        path = self.output / relative
        request = {"model": MODEL, "temperature": 0, "max_tokens": 16384 if kind == "confirmation" else 4096,
                   "messages": messages, "response_format": {"type": "json_schema", "json_schema": {
                       "name": "risk_v5_" + kind, "strict": True, "schema": self.schemas[kind]}}}
        request_hash = digest(request)
        prior_attempts = []
        if path.exists():
            cached = load(path)
            if cached.get("request_sha256") != request_hash:
                raise StopRun("Cached request mismatch: " + relative)
            if (cached["status"] == "OK" or not self.retry_errors or cached.get("refusal")
                    or cached.get("finish_reason") == "content_filter"):
                return cached
            prior_attempts = cached.get("attempts", [])
        if prep.TOKENIZER is not None:
            input_tokens = sum(len(prep.TOKENIZER.encode(m["content"])) for m in messages)
            if input_tokens + request["max_tokens"] > 126000:
                result = {"status": "INPUT_TOO_LONG", "record_id": record_id, "api_called": False,
                          "input_tokens": input_tokens, "request_sha256": request_hash}
                save(path, result)
                return result
        save(path.with_suffix(".request.json"), {"request_sha256": request_hash, "request": request})
        attempts = prior_attempts
        for attempt in range(4):
            if self.calls >= self.max_calls:
                raise StopRun("Invocation request cap reached; cached stages can be resumed")
            delay = self.pause - (time.monotonic() - self.last_call)
            if delay > 0:
                time.sleep(delay)
            self.calls += 1; self.state["attempted_calls"] += 1
            self.state.update({"last_started_at_utc": now(), "last_stage": relative})
            save(self.state_path, self.state)
            start = time.monotonic()
            row = {"attempt": len(attempts) + 1, "status": "ERROR", "started_at_utc": now()}
            fatal, retriable = False, False
            try:
                response = self.sdk.chat.completions.create(**request)
                row.update({"response_id": response.id, "response_model": response.model,
                            "usage": response.usage.model_dump() if response.usage else None,
                            "system_fingerprint": getattr(response, "system_fingerprint", None)})
                choice = response.choices[0]
                row.update({"finish_reason": choice.finish_reason, "refusal": getattr(choice.message, "refusal", None),
                            "content": choice.message.content or ""})
                if response.model != MODEL:
                    raise StopRun("Returned model differs from requested snapshot")
                if choice.finish_reason != "stop" or row["refusal"]:
                    raise ValueError("Incomplete/refused response: " + str(choice.finish_reason))
                answer = json.loads(row["content"])
                errors = legacy.validate(answer, self.schemas[kind])
                if errors or answer.get("record_id") != record_id:
                    raise ValueError("; ".join(errors) or "record_id differs")
                row.update({"status": "OK", "answer": answer})
                self.consecutive_network_failures = 0
            except Exception as exc:
                error = re.sub(r"sk-[A-Za-z0-9_.-]+", "[redacted-key]", str(exc).replace(self.secret, "[redacted-key]"))
                row.update({"error_type": type(exc).__name__, "error": error[:1200]})
                fatal = isinstance(exc, StopRun) or type(exc).__name__ in ("AuthenticationError", "PermissionDeniedError", "BadRequestError")
                retriable = type(exc).__name__ in ("APIConnectionError", "APITimeoutError", "RateLimitError", "InternalServerError")
            self.last_call = time.monotonic()
            row["elapsed_seconds"] = round(time.monotonic() - start, 3)
            attempts.append(row)
            result = {**row, "record_id": record_id, "request_sha256": request_hash,
                      "attempts": attempts, "api_called": True}
            save(path, result)
            print(f"[{self.state['attempted_calls']}] {relative} {row['status']}", flush=True)
            if fatal:
                raise StopRun(row["error"])
            if row["status"] == "OK" or not retriable:
                return result
            if attempt < 3:
                time.sleep((2, 5, 15)[attempt])
        self.consecutive_network_failures += 1
        if self.consecutive_network_failures >= 3:
            raise StopRun("Three stages exhausted network retries; stopping before sending more articles")
        return result


def verified_stage(client, relative, messages, kind, rid, paragraphs, validate_answer):
    first = client.stage(relative, messages, kind, rid)
    if first["status"] != "OK":
        return first, None
    answer, repairs, checks = restore_quotes(first["answer"], paragraphs)
    errors = validate_answer(answer)
    audit = {"first_raw_quote_checks": checks, "deterministic_repairs": repairs,
             "validation_errors": errors, "response_path": relative}
    if errors:
        retry = str(Path(relative).with_name(Path(relative).stem + "_validation_retry1.json"))
        correction = {"role": "user", "content": (
            "Controller validation found the following output-contract errors. Repeat the same task, "
            "fixing these errors using ONLY original text already supplied. Keep all supported propositions "
            "and candidate mappings; do not discard a supported claim just to pass validation. "
            "If needed, request context instead of inventing evidence. Errors:\n" + json.dumps(errors, ensure_ascii=False))}
        repaired = client.stage(retry, messages + [{"role": "assistant", "content": first["content"]}, correction], kind, rid)
        audit["validation_retry_path"] = retry
        if repaired["status"] != "OK":
            save(client.output / Path(relative).with_suffix(".validation.json"), audit)
            return repaired, None
        answer, more_repairs, retry_checks = restore_quotes(repaired["answer"], paragraphs)
        audit.update({"retry_raw_quote_checks": retry_checks, "retry_deterministic_repairs": more_repairs,
                      "final_validation_errors": validate_answer(answer)})
        errors = audit["final_validation_errors"]
    audit["validated_answer"] = answer
    save(client.output / Path(relative).with_suffix(".validation.json"), audit)
    if errors:
        return {"status": "VALIDATION_ERROR", "record_id": rid, "errors": errors}, None
    return {"status": "OK", "record_id": rid}, answer


def confirm_article(client, article, candidates, templates, max_rounds=6):
    rid = str(article["record_id"])
    paragraphs = prep.paragraph_map(article)
    controller = ContextController(paragraphs, candidates)
    rounds = []
    for number in range(1, max_rounds + 1):
        metadata = controller.snapshot()
        relative = f"raw/call3/{rid}_round{number:02d}.json"
        save(client.output / Path(relative).with_suffix(".context.json"), metadata)
        messages = [{"role": "system", "content": templates["call3_system"]}, {"role": "user", "content": render(
            templates["call3_user"], record_id=rid, context_review_status=controller.status,
            candidate_context_package=legacy.local_package(candidates, paragraphs),
            additional_context_package=controller.additional())}]
        allowed = controller.allowed()
        result, answer = verified_stage(client, relative, messages, "confirmation", rid, paragraphs,
            lambda value: confirmation_errors(value, paragraphs, candidates, allowed))
        rounds.append({"round": number, "response_path": relative, "context": metadata, "status": result["status"]})
        if answer is None:
            return {"record_id": rid, "status": result["status"], "failed_stage": relative,
                    "rounds": rounds, "controller_events": controller.events}
        if controller.status == "complete":
            unresolved = [d for d in answer["candidate_decisions"] if d["decision"] == "unresolved"]
            if answer["context_requests"] or unresolved:
                return {"record_id": rid, "status": "UNRESOLVED", "confirmation": answer,
                        "rounds": rounds, "controller_events": controller.events}
            return {"record_id": rid, "status": "OK", "answer": final_projection(answer),
                    "confirmation": answer, "rounds": rounds, "controller_events": controller.events,
                    "context_review_status": "complete", "final_unit_id_map": {
                        unit["unit_id"]: f"U{i:02d}" for i, unit in enumerate(answer["units"], 1)}}
        controller.accept_review_round(number)
        if not controller.review_completed:
            controller.expand(answer["context_requests"], number)
    return {"record_id": rid, "status": "CONTEXT_LIMIT", "rounds": rounds,
            "controller_events": controller.events, "context_review_status": controller.status}


def extract_article(client, article, templates, max_rounds):
    rid = str(article["record_id"])
    paragraphs = prep.paragraph_map(article)
    chunks = prep.paragraph_chunks(paragraphs)
    candidates, paths = [], []
    for phase in (1, 2):
        for number, pids in enumerate(chunks, 1):
            relative = f"raw/call{phase}/{rid}_{number:03d}.json"
            supplied = {pid: paragraphs[pid] for pid in pids}
            # Call 1 includes the title separately, even if outside this block.
            if phase == 1:
                supplied["P000"] = paragraphs["P000"]
            values = {"record_id": rid, "title": article["title"],
                      "paragraph_numbered_article": "\n".join(f"[{pid}] {paragraphs[pid]}" for pid in pids),
                      "list of C01..C_n quotes": "\n".join(c["candidate_id"] + ": " + c["quote"] for c in candidates)}
            messages = [{"role": "system", "content": templates[f"call{phase}_system"]},
                        {"role": "user", "content": render(templates[f"call{phase}_user"], **values)}]
            result, answer = verified_stage(client, relative, messages, "candidate", rid, supplied,
                                            lambda value: candidate_errors(value, supplied))
            paths.append(relative)
            if answer is None:
                return {"record_id": rid, "status": result["status"], "failed_stage": relative,
                        "discovery_stage_paths": paths, "discovery_stages_complete": False}
            candidates = merge_candidates(candidates, answer["candidates"], paragraphs, relative)
    candidates = freeze_candidates(candidates, paragraphs)
    save(client.output / "candidates" / f"{rid}.json", {"record_id": rid, "candidates": candidates})
    result = confirm_article(client, article, candidates, templates, max_rounds)
    result.update({"discovery_stages_complete": True, "discovery_stage_paths": paths,
                   "candidate_count": len(candidates)})
    return result
