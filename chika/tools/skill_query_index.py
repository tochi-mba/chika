"""SKILL.md retrieval index — chunk + BM25 ranking, cached on disk.

Why BM25 (and not embeddings) for the first version
---------------------------------------------------

SKILL.md content is technical: tool names, parameter shapes, code blocks,
short imperative rules. BM25 — the standard sparse retrieval scoring
function — is empirically competitive with dense embeddings for this
shape of corpus, often better because exact identifier matches (e.g.
``plan_set``, ``task_id``) score perfectly. It also has zero external
dependencies, runs in microseconds, is deterministic across runs, and
doesn't need an API key. Embeddings can layer on top later as a setting.

What gets indexed
-----------------

Each SKILL.md is split on top-level ``## `` headings (with the leading
``# `` title kept as section ``preface``). Sections larger than
``_MAX_CHUNK_CHARS`` are sub-split on blank lines so a giant
"Reference patterns" block doesn't drown out smaller, more specific
sections. Each chunk keeps its heading path so the agent can see WHERE
each result came from.

Cache lifecycle
---------------

Index files live at ``data/skill_index/<skill>.json``. On each query we
compare the cached ``mtime`` against the SKILL.md's current mtime — any
change triggers a rebuild. No background refresh.
"""
from __future__ import annotations

import json
import math
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent.parent
_SKILLS_DIR = _REPO / "chika" / "skills"
_CACHE_DIR = _REPO / "data" / "skill_index"

_MAX_CHUNK_CHARS = 1200       # split sections bigger than this
# Drop tiny noise chunks. Tuned just-low-enough to keep real one-line
# instructions ("Call cleanup_tool when finished.") which tend to land
# around 30-50 chars.
_MIN_CHUNK_CHARS = 25
_BM25_K1 = 1.5
_BM25_B  = 0.75


# ── Skill folder resolution (mirrors skill_doc_tool) ───────────────────────


def _resolve_skill_dir(name: str) -> Path | None:
    candidates = {name, f"{name}_skill", name.lower(), f"{name.lower()}_skill"}
    for cand in candidates:
        path = _SKILLS_DIR / cand
        if path.is_dir():
            return path
    return None


def _find_skill_doc(skill_name: str) -> Path | None:
    skill_dir = _resolve_skill_dir(skill_name)
    if skill_dir is None:
        return None
    for entry in skill_dir.iterdir():
        if entry.is_file() and entry.name.lower() == "skill.md":
            return entry
    return None


# ── Tokenisation ──────────────────────────────────────────────────────────

# Compact stopword list — enough to keep BM25 noise down without erasing
# meaningful technical terms. Code identifiers (``task_id``,
# ``plan_set``) are deliberately split on underscores so a query for
# "plan_set" matches both "plan" and "set".
_STOPWORDS = frozenset((
    "a", "an", "the", "of", "in", "on", "for", "to", "and", "or",
    "is", "are", "be", "this", "that", "it", "as", "with", "by",
    "from", "at", "you", "your", "i", "we", "if", "then", "but",
    "so", "do", "does", "can", "should", "would", "could", "will",
    "into", "out", "up", "down", "over", "under", "than", "also",
    "use", "uses", "using", "used",
))

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return [
        t.lower() for t in _TOKEN_RE.findall(text)
        if t.lower() not in _STOPWORDS and len(t) > 1
    ]


# ── Chunking ──────────────────────────────────────────────────────────────


@dataclass
class Chunk:
    skill:    str
    heading:  str        # e.g. "Conventions" / "Tools" / "preface"
    body:     str        # raw markdown body of the section
    tokens:   list[str] = field(default_factory=list)
    length:   int = 0    # token count (cached for BM25 length norm)


def _split_oversize(heading: str, body: str) -> list[str]:
    """Sub-split a too-large section on blank lines, keeping each piece
    under :data:`_MAX_CHUNK_CHARS`."""
    if len(body) <= _MAX_CHUNK_CHARS:
        return [body]
    parts: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for para in body.split("\n\n"):
        if cur_len + len(para) + 2 > _MAX_CHUNK_CHARS and cur:
            parts.append("\n\n".join(cur))
            cur, cur_len = [], 0
        cur.append(para)
        cur_len += len(para) + 2
    if cur:
        parts.append("\n\n".join(cur))
    return parts


def _chunk_markdown(skill: str, doc: str) -> list[Chunk]:
    """Split a SKILL.md into chunks keyed by ``## `` headings.

    The ``# Title`` line and any prose before the first ``## `` becomes
    a chunk with heading ``"preface"``.
    """
    chunks: list[Chunk] = []
    # Split on top-level ## headings only — sub-headings stay inside.
    # Use a regex that captures the heading text + the following body
    # (everything up to the next ## or EOF).
    pattern = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
    matches = list(pattern.finditer(doc))

    # Anything before the first ## is the "preface" (title + intro).
    first_offset = matches[0].start() if matches else len(doc)
    preface = doc[:first_offset].strip()
    if len(preface) >= _MIN_CHUNK_CHARS:
        for i, body in enumerate(_split_oversize("preface", preface)):
            heading = "preface" if i == 0 else f"preface (part {i+1})"
            chunks.append(_make_chunk(skill, heading, body))

    for idx, match in enumerate(matches):
        heading = match.group(1).strip()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(doc)
        body = doc[match.end():end].strip()
        if len(body) < _MIN_CHUNK_CHARS:
            continue
        for i, sub in enumerate(_split_oversize(heading, body)):
            label = heading if i == 0 else f"{heading} (part {i+1})"
            chunks.append(_make_chunk(skill, label, sub))
    return chunks


def _make_chunk(skill: str, heading: str, body: str) -> Chunk:
    tokens = _tokenize(f"{heading}\n{body}")
    return Chunk(skill=skill, heading=heading, body=body,
                 tokens=tokens, length=len(tokens))


# ── BM25 index ────────────────────────────────────────────────────────────


@dataclass
class BM25Index:
    skill:      str
    doc_path:   str
    doc_mtime:  float
    chunks:     list[Chunk]
    avg_length: float
    df:         dict[str, int]   # document frequency: token → count of chunks containing it

    def score_query(self, query: str, k: int = 3) -> list[tuple[Chunk, float]]:
        """Return the top-k ``(chunk, score)`` pairs for ``query``."""
        q_tokens = _tokenize(query)
        if not q_tokens:
            return []
        n = len(self.chunks) or 1
        results: list[tuple[Chunk, float]] = []
        for chunk in self.chunks:
            score = 0.0
            tf_chunk = Counter(chunk.tokens)
            for qt in q_tokens:
                tf = tf_chunk.get(qt, 0)
                if not tf:
                    continue
                df = self.df.get(qt, 0) or 1
                idf = math.log((n - df + 0.5) / (df + 0.5) + 1)
                norm = chunk.length / max(self.avg_length, 1)
                score += idf * (tf * (_BM25_K1 + 1)) / (
                    tf + _BM25_K1 * (1 - _BM25_B + _BM25_B * norm)
                )
            if score > 0:
                results.append((chunk, score))
        results.sort(key=lambda p: p[1], reverse=True)
        return results[:k]

    # ── Persistence ─────────────────────────────────────────────────────

    def to_json(self) -> dict:
        return {
            "skill":      self.skill,
            "doc_path":   self.doc_path,
            "doc_mtime":  self.doc_mtime,
            "avg_length": self.avg_length,
            "df":         self.df,
            "chunks": [
                {
                    "skill":   c.skill,
                    "heading": c.heading,
                    "body":    c.body,
                    "tokens":  c.tokens,
                    "length":  c.length,
                }
                for c in self.chunks
            ],
        }

    @classmethod
    def from_json(cls, data: dict) -> BM25Index:
        return cls(
            skill=data["skill"],
            doc_path=data["doc_path"],
            doc_mtime=float(data["doc_mtime"]),
            avg_length=float(data["avg_length"]),
            df=dict(data["df"]),
            chunks=[
                Chunk(
                    skill=c["skill"], heading=c["heading"], body=c["body"],
                    tokens=list(c["tokens"]), length=int(c["length"]),
                )
                for c in data["chunks"]
            ],
        )


def _build_index(skill: str, doc_path: Path) -> BM25Index:
    doc = doc_path.read_text(encoding="utf-8")
    chunks = _chunk_markdown(skill, doc)
    if not chunks:
        # Build an empty index so the caller still gets a valid object.
        return BM25Index(
            skill=skill, doc_path=str(doc_path),
            doc_mtime=doc_path.stat().st_mtime,
            chunks=[], avg_length=1.0, df={},
        )
    avg_length = sum(c.length for c in chunks) / len(chunks)
    df: Counter = Counter()
    for chunk in chunks:
        for token in set(chunk.tokens):
            df[token] += 1
    return BM25Index(
        skill=skill,
        doc_path=str(doc_path),
        doc_mtime=doc_path.stat().st_mtime,
        chunks=chunks,
        avg_length=avg_length,
        df=dict(df),
    )


# ── Cache layer ───────────────────────────────────────────────────────────


def _cache_path(skill: str) -> Path:
    return _CACHE_DIR / f"{skill}.json"


def get_index(skill: str) -> BM25Index | None:
    """Return a fresh-or-cached BM25 index for ``skill``.

    Cache key is the SKILL.md mtime — any save invalidates the cache. A
    missing SKILL.md returns ``None`` so callers can surface a clean
    error.
    """
    doc_path = _find_skill_doc(skill)
    if doc_path is None:
        return None

    skill_dir = doc_path.parent
    canonical = skill_dir.name.removesuffix("_skill") or skill_dir.name

    cache = _cache_path(canonical)
    current_mtime = doc_path.stat().st_mtime

    if cache.exists():
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            if abs(float(data.get("doc_mtime", 0)) - current_mtime) < 1e-6:
                return BM25Index.from_json(data)
        except Exception:
            pass  # corrupt cache → rebuild

    index = _build_index(canonical, doc_path)
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(index.to_json(), indent=2), encoding="utf-8")
    except Exception:
        # Cache write is best-effort — the index works in-memory regardless.
        pass
    return index


def query(skill: str, query_text: str, k: int = 3) -> dict:
    """Top-k SKILL.md chunks ranked for ``query_text``.

    Returns a dict — never raises on missing skill / empty doc / empty
    query, so the workflow engine can serialise it cleanly.
    """
    if not isinstance(skill, str) or not skill.strip():
        return {"error": "skill must be a non-empty string"}
    if not isinstance(query_text, str) or not query_text.strip():
        return {"error": "query must be a non-empty string"}

    t0 = time.monotonic()
    index = get_index(skill)
    if index is None:
        return {
            "error": "skill_not_found",
            "skill": skill,
            "hint": (
                f"No SKILL.md found for {skill!r}. "
                "Try /skills to see registered names."
            ),
        }
    if not index.chunks:
        return {
            "error":     "empty_doc",
            "skill":     index.skill,
            "doc_path":  index.doc_path,
            "hint": (
                "SKILL.md is too small to chunk — call skill_load to read "
                "the whole thing instead."
            ),
        }

    k = max(1, min(int(k), 10))
    top = index.score_query(query_text, k=k)
    duration_ms = int((time.monotonic() - t0) * 1000)
    return {
        "skill":      index.skill,
        "query":      query_text,
        "chunks": [
            {
                "heading": chunk.heading,
                "body":    chunk.body,
                "score":   round(score, 3),
            }
            for chunk, score in top
        ],
        "total_chunks_searched": len(index.chunks),
        "duration_ms":           duration_ms,
    }


__all__ = [
    "BM25Index",
    "Chunk",
    "_build_index",
    "_chunk_markdown",
    "_tokenize",
    "get_index",
    "query",
]
