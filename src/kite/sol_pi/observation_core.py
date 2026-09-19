"""ObservationPack core helpers (ported from NVlabs/SoL-Pi)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

THRESHOLD_BYTES = 10 * 1024
FULL_SENDS = 2
PLACEHOLDER_EXCERPT_BYTES = 1024
CHARS_PER_TOKEN = 4
EVIDENCE_REDUCER_RECEIPT_PREFIX = "sol_pi_evidence_receipt_v1"
OBSERVATION_ID_PATTERN = re.compile(r"^obs_[a-f0-9]{24}$")


@dataclass(frozen=True, slots=True)
class Observation:
    id: str
    content_hash: str
    file_path: Path
    tool_name: str
    text: str
    bytes: int
    lines: int
    tokens: int


def sha256_hex(value: str | bytes) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def estimate_tokens(text: str) -> int:
    return (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN


def count_lines(text: str) -> int:
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def is_observation_id(obs_id: str) -> bool:
    return bool(OBSERVATION_ID_PATTERN.match(obs_id))


def observation_path(runtime_root: Path, obs_id: str) -> Path:
    return runtime_root / "observation-pack" / "objects" / f"{obs_id}.txt"


def contains_reducer_receipt(text: str) -> bool:
    return any(line == EVIDENCE_REDUCER_RECEIPT_PREFIX for line in text.split("\n"))


def create_observation(tool_name: str, tool_call_id: str, text: str, runtime_root: Path) -> Observation | None:
    if contains_reducer_receipt(text):
        return None
    body = text.encode("utf-8")
    if len(body) <= THRESHOLD_BYTES:
        return None
    content_hash = sha256_hex(body)
    identity = f"{tool_name}\0{tool_call_id}\0{content_hash}"
    obs_id = f"obs_{sha256_hex(identity)[:24]}"
    return Observation(
        id=obs_id,
        content_hash=content_hash,
        file_path=observation_path(runtime_root, obs_id),
        tool_name=tool_name,
        text=text,
        bytes=len(body),
        lines=count_lines(text),
        tokens=estimate_tokens(text),
    )


def ensure_stored(observation: Observation) -> None:
    observation.file_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if observation.file_path.exists():
        existing = observation.file_path.read_bytes()
        if sha256_hex(existing) != observation.content_hash:
            raise ValueError(f"Content-addressed observation hash mismatch for {observation.id}")
        if len(existing) != observation.bytes:
            raise ValueError(f"Content-addressed observation size mismatch for {observation.id}")
        return
    observation.file_path.write_text(observation.text, encoding="utf-8")


def _complete_line_excerpt(text: str, budget_bytes: int, from_end: bool) -> str:
    lines = re.split(r"(?<=\n)", text)
    selected: list[str] = []
    selected_bytes = 0
    index = len(lines) - 1 if from_end else 0
    while 0 <= index < len(lines):
        line = lines[index]
        line_bytes = len(line.encode("utf-8"))
        if selected_bytes + line_bytes > budget_bytes:
            break
        if from_end:
            selected.insert(0, line)
        else:
            selected.append(line)
        selected_bytes += line_bytes
        index += -1 if from_end else 1
    return "".join(selected)


def placeholder_for(observation: Observation) -> str:
    head_budget = PLACEHOLDER_EXCERPT_BYTES // 2
    tail_budget = PLACEHOLDER_EXCERPT_BYTES - head_budget
    head = _complete_line_excerpt(observation.text, head_budget, False)
    tail = _complete_line_excerpt(observation.text, tail_budget, True)
    return "\n".join(
        [
            f"[large tool result replaced after its first {FULL_SENDS} provider requests]",
            f"id: {observation.id}",
            f"tool: {observation.tool_name}",
            f"original_bytes: {observation.bytes}",
            f"original_lines: {observation.lines}",
            f"estimated_tokens: {observation.tokens}",
            f'retrieve: call obs_recall with {{"id":"{observation.id}","offset":0}}; continue with returned next_offset',
            f"[first complete lines, up to {head_budget} bytes]",
            head,
            f"[middle omitted; last complete lines, up to {tail_budget} bytes]",
            tail,
            f"[{observation.bytes} original bytes omitted]",
        ]
    )


@dataclass(frozen=True, slots=True)
class RecallChunk:
    text: str
    bytes: int
    lines: int
    next_offset: int
    eof: bool


def read_recall_chunk(path: Path, offset: int, *, max_bytes: int, max_lines: int) -> RecallChunk:
    data = path.read_bytes()
    if offset < 0 or offset > len(data):
        raise ValueError("offset out of range")
    end = min(len(data), offset + max_bytes)
    while end > offset and end < len(data) and (data[end] & 0xC0) == 0x80:
        end -= 1
    chunk = data[offset:end]
    text = chunk.decode("utf-8", errors="replace")
    lines = count_lines(text)
    if lines > max_lines:
        parts = text.splitlines(keepends=True)[:max_lines]
        text = "".join(parts)
        chunk = text.encode("utf-8")
        end = offset + len(chunk)
        lines = max_lines
    return RecallChunk(
        text=text,
        bytes=len(chunk),
        lines=lines,
        next_offset=end,
        eof=end >= len(data),
    )
