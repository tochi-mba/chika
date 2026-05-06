"""Regenerate ``data/skill_summaries/<skill_id>.json`` from current SKILL.md.

Run after editing a SKILL.md to commit a fresh summary alongside the
content change. CI gates on hash match (the summary's stored SHA-256
must match the SKILL.md bytes), so without this script a contributor's
PR fails the drift gate and they don't know the remediation.

Usage:

    python scripts/regenerate_skill_summaries.py
        # uses the configured provider (anthropic by default), regens
        # any skill whose hash drifted, leaves fresh ones alone

    python scripts/regenerate_skill_summaries.py --force
        # regen every skill regardless of cache freshness

    python scripts/regenerate_skill_summaries.py --skill git_skill
        # regen one skill only

    python scripts/regenerate_skill_summaries.py --provider anthropic
        # explicit provider override

    python scripts/regenerate_skill_summaries.py --dry-run
        # show what would regenerate without calling the LLM

Edge cases handled
------------------
- No API key configured → exits 2 with a clear message naming the
  expected env var. We never silently produce empty caches.
- LLM returns malformed JSON → that skill is skipped with a warning,
  exit code 3 at the end if any skills failed.
- Network failure mid-run → still commits whatever did succeed; the
  next run re-tries the failures.
- ``--check`` mode for CI: exits 1 if any committed summary is stale.

This is the contributor-facing companion to
``chika.skills.summarizer`` (the runtime path). Both go through the
same Pydantic validation + hash discipline.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)
log = logging.getLogger(__name__)

from chika.skills.summarizer import (  # noqa: E402
    CachedSummary,
    cache_path,
    compute_hash,
    generate_summary_async,
    load_summary,
    save_summary,
)


def _discover_skill_md_files() -> dict[str, Path]:
    """Map ``skill_id`` → path to its SKILL.md.

    skill_id is the directory name under ``chika/skills/``.
    """
    skills_dir = REPO_ROOT / "chika" / "skills"
    out: dict[str, Path] = {}
    for d in sorted(skills_dir.iterdir()):
        if not d.is_dir():
            continue
        if d.name.startswith("_"):
            continue
        skill_md = d / "SKILL.md"
        if skill_md.is_file() and skill_md.stat().st_size > 0:
            out[d.name] = skill_md
    return out


def _llm_callable_from_provider(provider: str):
    """Return an async LLM completion fn matching the summarizer's
    expected signature: ``async def call(*, system, user, max_tokens)
    -> str``.

    Lazy-imports per-provider clients so the script works even when
    only one provider's SDK is installed locally.
    """
    if provider == "anthropic":
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print(
                "ANTHROPIC_API_KEY not set. Either:\n"
                "  - export ANTHROPIC_API_KEY=sk-ant-...\n"
                "  - pass --provider openai (and OPENAI_API_KEY)\n"
                "  - run --dry-run to see what would regenerate",
                file=sys.stderr,
            )
            sys.exit(2)
        try:
            from anthropic import AsyncAnthropic
        except ImportError:
            print(
                "anthropic package not installed. Run: pip install anthropic",
                file=sys.stderr,
            )
            sys.exit(2)
        client = AsyncAnthropic(api_key=api_key)
        model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

        async def call(*, system: str, user: str, max_tokens: int) -> str:
            resp = await client.messages.create(
                model=model,
                system=system,
                messages=[{"role": "user", "content": user}],
                max_tokens=max_tokens,
            )
            # Anthropic returns a list of content blocks; the first
            # text block is what we want.
            for block in resp.content:
                if getattr(block, "type", "") == "text":
                    return block.text
            return ""

        return call

    if provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            print("OPENAI_API_KEY not set", file=sys.stderr)
            sys.exit(2)
        try:
            from openai import AsyncOpenAI
        except ImportError:
            print("openai package not installed", file=sys.stderr)
            sys.exit(2)
        client = AsyncOpenAI(api_key=api_key)
        model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

        async def call(*, system: str, user: str, max_tokens: int) -> str:
            resp = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            return resp.choices[0].message.content or ""

        return call

    print(f"unknown provider: {provider}", file=sys.stderr)
    sys.exit(2)


async def _generate_one(skill_id: str, skill_md: Path, llm) -> bool:
    """Generate + save the summary for one skill. Returns success."""
    text = skill_md.read_text(encoding="utf-8", errors="replace")
    log.info("  · %s (%d chars)", skill_id, len(text))
    summary = await generate_summary_async(skill_id, text, llm)
    if summary is None:
        log.warning("    failed — see preceding log")
        return False
    cached = CachedSummary(
        skill_id=skill_id,
        sha256=compute_hash(skill_md),
        summary=summary,
        generated_at=datetime.now(UTC).isoformat(),
    )
    save_summary(cached, root=REPO_ROOT)
    log.info("    wrote %s", cache_path(skill_id, REPO_ROOT).relative_to(REPO_ROOT))
    return True


async def run(*, force: bool, only: str | None, provider: str,
              dry_run: bool, check: bool) -> int:
    skills = _discover_skill_md_files()
    if only:
        if only not in skills:
            print(f"unknown skill: {only}. options: {sorted(skills)}", file=sys.stderr)
            return 2
        skills = {only: skills[only]}

    needs_regen: list[tuple[str, Path]] = []
    for skill_id, skill_md in skills.items():
        current_hash = compute_hash(skill_md)
        cached = load_summary(skill_id, root=REPO_ROOT)
        if force or cached is None or cached.sha256 != current_hash:
            needs_regen.append((skill_id, skill_md))

    if check:
        if needs_regen:
            print("DRIFT: the following skill summaries are stale:", file=sys.stderr)
            for sid, _ in needs_regen:
                print(f"  · {sid}", file=sys.stderr)
            print(
                "\nRun: python scripts/regenerate_skill_summaries.py",
                file=sys.stderr,
            )
            return 1
        print(f"all {len(skills)} skill summaries are up to date.")
        return 0

    if not needs_regen:
        print(f"all {len(skills)} summaries are fresh.")
        return 0

    print(f"regenerating {len(needs_regen)} summary(ies):")
    for sid, _ in needs_regen:
        print(f"  · {sid}")

    if dry_run:
        print("\n--dry-run set; nothing was written.")
        return 0

    llm = _llm_callable_from_provider(provider)
    failures = 0
    for sid, skill_md in needs_regen:
        ok = await _generate_one(sid, skill_md, llm)
        if not ok:
            failures += 1

    if failures:
        print(f"\n{failures}/{len(needs_regen)} regeneration(s) failed.", file=sys.stderr)
        return 3
    print(f"\n✓ regenerated {len(needs_regen)} summary(ies).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--force", action="store_true",
                         help="Regenerate even fresh summaries.")
    parser.add_argument("--skill", default=None,
                         help="Regenerate only this skill (e.g. git_skill).")
    parser.add_argument("--provider", default="anthropic",
                         choices=("anthropic", "openai"),
                         help="LLM provider for the summarizer call.")
    parser.add_argument("--dry-run", action="store_true",
                         help="Print what would regenerate, don't call the LLM.")
    parser.add_argument("--check", action="store_true",
                         help="CI mode: exit 1 if any committed summary is stale.")
    args = parser.parse_args(argv)
    return asyncio.run(run(
        force=args.force,
        only=args.skill,
        provider=args.provider,
        dry_run=args.dry_run,
        check=args.check,
    ))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
