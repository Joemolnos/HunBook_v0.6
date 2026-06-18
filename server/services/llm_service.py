from __future__ import annotations
from typing import Any, Dict, Iterator, Tuple, Callable, Optional
import json
import time
import logging
import os

from config import groq_client
from stats import GenerationStatistics
from ..schemas import StructureParams, SectionParams, MCPConfig
from .mcp_service import call_mcp_tools_multiple as _mcp_multi
from .tpm_throttler import TpmThrottler
from .quality_context import build_quality_context_block, COMPACT_QUALITY_REMINDER


def _build_system_structure(num_chapters: int) -> str:
    lo = max(3, num_chapters - 3)
    hi = num_chapters + 3
    return (
        "You are an expert book planner and editor. Output ONLY valid JSON. "
        "Keys are chapter titles, values are either a description string (leaf) or a nested object (sub-chapters). "
        "\n\nQuality rules for the outline:\n"
        f"1. Generate {lo}–{hi} substantive chapters that together provide COMPLETE coverage of the subject.\n"
        "2. Every chapter must cover DIFFERENT content — zero overlap, zero duplication between chapters.\n"
        "3. Arrange chapters in a logical progressive order: foundations → mechanisms → applications → advanced → future.\n"
        "4. Each leaf description must be SPECIFIC: name the concrete sub-topics, facts, or debates that chapter will address. "
        "Avoid vague phrases like 'discusses various aspects' or 'provides an overview'.\n"
        "5. Chapter titles must be concise (3–7 words), informative, and written in the same language as the subject.\n"
        "6. Omit introduction/foreword/preface/summary chapters unless explicitly requested.\n"
        "7. Leaf values: plain text, 1–2 sentences, no markdown or lists."
    )

logger = logging.getLogger(__name__)
SECTION_PACING_S = float(os.getenv("SECTION_PACING_S", "0"))  # optional pacing between sections
MAX_SECTIONS = int(os.getenv("MAX_SECTIONS", "50") or 50)
MIN_SECTIONS = int(os.getenv("MIN_SECTIONS", "3") or 3)


def _language_instruction(language: str) -> str:
    if not language:
        return ""
    return f"Write all content in { 'Hungarian' if language.lower().startswith('hu') else language }."


_STYLE_GUIDE = {
    "akadémikus": (
        "Write in an academic style: use precise terminology, cite mechanisms and evidence, "
        "structure arguments formally with claims followed by supporting reasoning. "
        "Use hedged language where appropriate ('research suggests', 'evidence indicates')."
    ),
    "közérthető": (
        "Write in a clear, accessible style: use plain language, explain technical terms when introduced, "
        "favour short sentences and concrete analogies. Avoid jargon without explanation."
    ),
    "narratív": (
        "Write in a narrative style: open sections with a compelling scene or anecdote, "
        "use storytelling structure, connect facts to human experience, maintain forward momentum."
    ),
    "technikai": (
        "Write in a technical style: precise, implementation-focused, include specific numbers "
        "and parameters where relevant, use code-style terminology, favour structured lists for procedures."
    ),
}

_LEVEL_GUIDE = {
    "általános": "Assume the reader has no prior knowledge; build from first principles.",
    "közép": "Assume basic familiarity; skip elementary definitions but explain intermediate concepts.",
    "egyetemi": "Assume undergraduate-level knowledge; engage with nuance and competing perspectives.",
    "szakértő": "Assume expert-level knowledge; use field-specific terminology without preamble.",
}

def _style_instruction(style: str | None, reading_level: str | None) -> str:
    parts = []
    if style:
        guide = _STYLE_GUIDE.get((style or "").lower().strip())
        parts.append(guide if guide else f"Use a {style} writing style.")
    if reading_level:
        guide = _LEVEL_GUIDE.get((reading_level or "").lower().strip())
        parts.append(guide if guide else f"Target reading level: {reading_level}.")
    return " ".join(parts)


def _length_instruction(target_length: int | None) -> str:
    # This is injected into the base system prompt; the precise per-sub-section word
    # target is handled by _plan_subsections instructions in the user message.
    words = target_length or 1200
    return (
        f"Each sub-section you write MUST be at least {max(400, words // max(1, _n_subsections(words)))} words. "
        "Do NOT stop early. Expand every point with examples, explanations, and analysis."
    )


def _flatten_structure(sections: Dict[str, Any], path: list[str] | None = None) -> list[dict[str, Any]]:
    """Flatten nested structure dict into an ordered list of items with path.
    Each item: {"title": str, "prompt": str, "path": [..]}
    Leaves are entries where value is str; nested dicts are traversed depth-first.
    """
    path = path or []
    items: list[dict[str, Any]] = []
    for title, content in sections.items():
        curr_path = path + [title]
        if isinstance(content, str):
            items.append({"title": title, "prompt": content, "path": curr_path})
        elif isinstance(content, dict):
            # container node; traverse deeper
            items.extend(_flatten_structure(content, curr_path))
        else:
            # unknown type; skip
            continue
    return items


def _outline_summary(sections: Dict[str, Any]) -> str:
    """Create a compact, single-line outline summary from the structure.
    Format: Title — sub1, sub2; NextTitle — ...
    """
    parts: list[str] = []
    for title, content in sections.items():
        if isinstance(content, dict):
            subs = ", ".join(content.keys())
            parts.append(f"{title}: {subs}")
        else:
            parts.append(title)
    return " | ".join(parts)[:4000]  # keep within reasonable token limit


def _is_intro_like(title: str) -> bool:
    t = (title or "").strip().lower()
    return any(k in t for k in [
        "bevezetés", "elozo", "előszó", "eloszo", "foreword", "introduction", "preface", "author",
    ])


def _is_conclusion_like(title: str) -> bool:
    t = (title or "").strip().lower()
    return any(k in t for k in [
        "összegzés", "összefoglal", "záró", "zarogondolat", "conclusion", "summary", "closing",
    ])


def _strip_intro_conclusion(sections: Dict[str, Any], include_intro: bool, include_conclusion: bool) -> Dict[str, Any]:
    """Remove intro/conclusion-like sections unless explicitly requested."""
    def filt(d: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for k, v in d.items():
            if isinstance(v, dict):
                vv = filt(v)
                # Keep container even if empty? Prefer drop if empty
                if vv:
                    out[k] = vv
                continue
            # leaf or unknown
            drop = (not include_intro and _is_intro_like(k)) or (not include_conclusion and _is_conclusion_like(k))
            if not drop:
                out[k] = v
        return out


def _ensure_min_leaves(sections: Dict[str, Any], min_leaves: int, subject: str) -> Dict[str, Any]:
    """If the outline has fewer than min_leaves leaves, return a simple fallback outline.
    The fallback provides neutral, non-intro/non-conclusion topics to avoid being stripped.
    """
    try:
        leaves = _flatten_structure(sections)
    except Exception:
        leaves = []
    if len(leaves) >= max(1, int(min_leaves or 1)):
        return sections
    subj = (subject or "Téma").strip()
    topics = [
        "Alapfogalmak és háttér",
        "Történeti háttér",
        "Fő komponensek és felépítés",
        "Működési elvek",
        "Gyakorlati alkalmazások",
        "Előnyök és kihívások",
        "Módszerek és eszközök",
        "Esettanulmányok",
        "Trendek és jövőkép",
        "Kitekintés",
    ]
    # Ensure we have at least min_leaves topics by repeating variants if necessary (cap by MAX_SECTIONS)
    need = max(1, int(min_leaves or 1))
    out: Dict[str, Any] = {}
    i = 0
    while i < need and i < MAX_SECTIONS:
        label = topics[i % len(topics)]
        out[f"Fejezet {i+1}"] = f"Részletes fejezet a(z) {subj} témában: {label}."
        i += 1
    return out

def _limit_leaves(sections: Dict[str, Any], max_leaves: int) -> Dict[str, Any]:
    """Return a copy of sections limited to the first max_leaves leaves (depth-first order).
    Leaves are entries where value is a string. Container nodes are preserved only if they have kept children.
    """
    count = 0

    def walk(d: Dict[str, Any]) -> Dict[str, Any]:
        nonlocal count
        out: Dict[str, Any] = {}
        for k, v in d.items():
            if isinstance(v, dict):
                child = walk(v)
                if child:
                    out[k] = child
            else:
                if count < max_leaves:
                    out[k] = v
                    count += 1
                else:
                    # skip extra leaves
                    continue
        return out

    try:
        return walk(sections or {})
    except Exception:
        return sections


# ─── Memory helpers ───────────────────────────────────────────────────────────

class LongTermMemory:
    """Condensed summaries of completed chapters — maintains cross-chapter consistency."""
    _MAX_KEPT = 8
    _SUMMARY_WORDS = 80

    def __init__(self) -> None:
        self._entries: list[tuple[str, str]] = []

    def add(self, title: str, content: str) -> None:
        words = content.split()
        summary = " ".join(words[: self._SUMMARY_WORDS])
        self._entries.append((title, summary))
        if len(self._entries) > self._MAX_KEPT:
            self._entries.pop(0)

    def context(self) -> str:
        if not self._entries:
            return ""
        lines = "\n".join(f"  - {t}: {s}…" for t, s in self._entries[-5:])
        return (
            "Long-term memory — previously written chapters "
            "(maintain consistency and avoid repeating content):\n" + lines + "\n"
        )


class ShortTermMemory:
    """Tail of the last generated sub-section — ensures seamless continuation within a chapter."""
    _TAIL_WORDS = 200

    def __init__(self) -> None:
        self._tail = ""

    def update(self, content: str) -> None:
        words = content.split()
        self._tail = " ".join(words[-self._TAIL_WORDS :])

    def context(self) -> str:
        if not self._tail:
            return ""
        return (
            "Short-term memory — the chapter text ends exactly here "
            "(continue seamlessly, do NOT repeat this):\n…" + self._tail + "\n"
        )

    def reset(self) -> None:
        self._tail = ""


# ─── Sub-section planning ──────────────────────────────────────────────────────

def _n_subsections(target_length: int | None) -> int:
    if not target_length or target_length <= 700:
        return 1
    if target_length <= 1400:
        return 2
    if target_length <= 2500:
        return 3
    return 4


def _plan_subsections(title: str, n: int, words_per_sub: int) -> list[dict]:
    """Return N sub-section generation plans with focused instructions and per-sub max_tokens."""
    # ~1.4 tokens/word for Hungarian + 30 % headroom
    sub_max_tokens = min(2500, max(900, int(words_per_sub * 1.85)))
    if n == 1:
        return [{
            "role": "full", "is_first": True, "is_last": True,
            "max_tokens": sub_max_tokens,
            "instruction": (
                f"[Segment 1/1 — complete chapter]\n"
                f"Write the COMPLETE chapter. Target at least {words_per_sub} words.\n"
                "Cover all key points from the chapter description with depth and concrete examples.\n"
                "Start with '# ' + chapter title as the only H1 heading. "
                "Use multiple H2/H3 sub-headings to structure the content."
            ),
        }]
    plans: list[dict] = []
    for i in range(n):
        is_first = i == 0
        is_last = i == n - 1
        pos = f"[Segment {i+1}/{n}]"
        if is_first:
            instr = (
                f"{pos} — Opening segment\n"
                f"Write the OPENING of this chapter. Target at least {words_per_sub} words.\n"
                "Cover: (a) introduce the topic and its significance, (b) provide necessary background/context, "
                "(c) explain the first 1–2 major sub-topics from the chapter description with full paragraphs, concrete examples, and analysis.\n"
                "Start with '# ' + chapter title as the H1 heading. "
                "Use H2/H3 sub-headings — aim for at least 2 H2 sections with 3+ paragraphs each."
            )
        elif is_last:
            instr = (
                f"{pos} — Closing segment\n"
                f"Write the CLOSING of this chapter. Target at least {words_per_sub} words.\n"
                "Cover the remaining sub-topics from the chapter description that have NOT yet been addressed in earlier segments. "
                "Add concrete case studies, data, or examples for each point. "
                "End with a synthesis paragraph that connects the chapter's key insights — "
                "but do NOT write a generic summary; instead highlight an implication or open question.\n"
                "Do NOT add an H1 heading — start directly with an H2 heading."
            )
        else:
            instr = (
                f"{pos} — Middle segment\n"
                f"Continue the chapter with the NEXT set of sub-topics. Target at least {words_per_sub} words.\n"
                "Pick up exactly where the previous segment ended (see short-term memory). "
                "Cover the next 1–2 sub-topics from the chapter description with full depth: "
                "each sub-topic gets its own H2 section with 3+ substantive paragraphs, specific examples, and analysis. "
                "Do NOT repeat or summarise what was already written.\n"
                "Do NOT add an H1 heading — start directly with an H2 heading."
            )
        plans.append({
            "role": "opening" if is_first else ("closing" if is_last else f"middle_{i}"),
            "is_first": is_first, "is_last": is_last,
            "max_tokens": sub_max_tokens,
            "instruction": instr,
        })
    return plans


# ──────────────────────────────────────────────────────────────────────────────

def _dedupe_titles(sections: Dict[str, Any]) -> Dict[str, Any]:
    seen = set()
    out: Dict[str, Any] = {}
    for k, v in sections.items():
        key = (k or "").strip().lower()
        if key in seen:
            continue
        seen.add(key)
        if isinstance(v, dict):
            out[k] = _dedupe_titles(v)
        else:
            out[k] = v
    return out


def _refine_structure_for_coherence(subject: str, extra_txt: str, draft: Dict[str, Any], params: StructureParams, client=None) -> Dict[str, Any]:
    """Ask the LLM to refine descriptions and improve coherence. Returns refined JSON or raises."""
    editor_system = (
        "You are an expert book editor. You will receive a DRAFT JSON outline for a book. "
        "Your task is to IMPROVE the outline — NOT reduce it.\n\n"
        "Rules:\n"
        "1. Keep ALL chapters from the draft — do NOT delete or merge chapters unless two are truly identical.\n"
        "2. Make each chapter description more SPECIFIC: replace vague phrases with concrete sub-topics, "
        "named concepts, debates, or examples that the chapter will actually cover.\n"
        "3. Ensure every chapter covers DIFFERENT content — rewrite overlapping descriptions so each is unique.\n"
        "4. Align chapter titles with the subject language and improve clarity if needed.\n"
        "5. Maintain consistent terminology throughout.\n"
        "6. Depth must not exceed the requested depth.\n"
        "Output JSON only as a mapping: titles -> string (description) or nested objects for sub-chapters."
    )
    user_text = (
        f"SUBJECT:\n{subject}\n\n"
        f"REQUESTED DEPTH: {params.depth}\n"
        + (f"ADDITIONAL USER INSTRUCTIONS:\n{extra_txt}\n\n" if extra_txt else "")
        + "DRAFT OUTLINE (JSON) — improve descriptions, keep all chapters:\n"
        + json.dumps(draft, ensure_ascii=False)
    )
    c = client or groq_client
    # Prefer a bounded timeout to avoid indefinite stalls
    try:
        c = c.with_options(timeout=60)
    except Exception:
        pass
    # Scale max_tokens for refinement proportional to chapter count
    refine_max_tokens = min(8192, max(params.max_tokens, (params.num_chapters or 15) * 150 + 500))
    completion = c.chat.completions.create(
        model=params.model,
        messages=[{"role": "system", "content": editor_system}, {"role": "user", "content": user_text}],
        temperature=max(0.0, min(0.4, float(params.temperature or 0.3))),  # keep this conservative
        max_tokens=refine_max_tokens,
        top_p=params.top_p,
        stream=False,
        response_format={"type": "json_object"},
    )
    content = completion.choices[0].message.content
    refined = json.loads(content)
    # Lightweight cleanup pass
    refined = _strip_intro_conclusion(refined, params.include_intro, params.include_conclusion)
    refined = _dedupe_titles(refined)
    return refined


def generate_book_structure_service(
    subject: str,
    params: StructureParams,
    client=None,
    mcp_config=None,  # Optional[List[MCPConfig]]
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Three-phase structure generation:
      Phase 1: Generate chapter TITLES only (lightweight, never truncated)
      Phase 2: Generate descriptions for each title (batch, separate call)
      Phase 3: Cleanup, dedupe, limit
    Returns (statistics_dict, structure_dict)
    """
    lang_instr = _language_instruction(params.language)
    intro_instr = (
        "Include an introduction and conclusion sections." if params.include_intro or params.include_conclusion
        else "Omit introduction and conclusion sections (foreword, author's note, summary)."
    )

    extra_txt = (params.extra_instructions or "").strip()

    # MCP pre-structure enrichment
    if mcp_config:
        try:
            mcp_context = _mcp_multi(mcp_config, subject, "pre_structure")
            if mcp_context:
                prefix = f"[MCP Context — use this to ground the outline]\n{mcp_context}"
                extra_txt = f"{prefix}\n\n{extra_txt}".strip()
                logger.info("MCP pre-structure context injected (%d chars)", len(mcp_context))
        except Exception as exc:
            logger.warning("MCP pre-structure call failed (non-fatal): %s", exc)

    num_ch = params.num_chapters or 15
    lo_ch = max(3, num_ch - 3)
    hi_ch = num_ch + 3

    client = client or groq_client
    try:
        client = client.with_options(timeout=60)
    except Exception:
        pass

    def _should_retry(err: Exception) -> bool:
        msg = str(err).lower()
        return "429" in msg or "rate limit" in msg or "timeout" in msg or "temporarily unavailable" in msg

    def _retry_delay(attempt: int) -> float:
        return min(2 ** attempt, 8) + 0.5 * (attempt + 1)

    # ── PHASE 1: Generate chapter titles only ─────────────────────────────────
    titles_system = (
        "You are an expert book planner. Output ONLY a valid JSON array of strings. "
        "Each string is a chapter title. No descriptions, no objects — just titles."
    )
    titles_user = (
        f"{lang_instr} {intro_instr}\n\n"
        f"Generate exactly {num_ch} chapter titles ({lo_ch}–{hi_ch} acceptable) for a comprehensive book on:\n"
        f"<subject>{subject}</subject>\n\n"
        "Rules:\n"
        "- Titles must be concise (3–7 words), informative, in the subject's language.\n"
        "- Cover the subject COMPLETELY — foundations to advanced to future.\n"
        "- Zero overlap between chapters.\n"
        "- Logical progressive order.\n"
        + (f"\nAdditional instructions:\n{extra_txt}\n" if extra_txt else "")
    ).strip()

    logger.info("Phase 1: generating %d chapter titles", num_ch)
    titles: list[str] = []
    total_input_tokens = 0
    total_output_tokens = 0
    total_time = 0.0

    for attempt in range(4):
        try:
            comp1 = client.chat.completions.create(
                model=params.model,
                messages=[
                    {"role": "system", "content": titles_system},
                    {"role": "user", "content": titles_user},
                ],
                temperature=params.temperature,
                max_tokens=min(2048, num_ch * 30 + 200),  # titles are very short
                top_p=params.top_p,
                stream=False,
                response_format={"type": "json_object"},
            )
            break
        except Exception as e:
            if not _should_retry(e) or attempt == 3:
                raise
            time.sleep(_retry_delay(attempt))

    usage1 = comp1.usage
    total_input_tokens += getattr(usage1, "prompt_tokens", 0) or 0
    total_output_tokens += getattr(usage1, "completion_tokens", 0) or 0
    total_time += (getattr(usage1, "prompt_time", 0) or 0) + (getattr(usage1, "completion_time", 0) or 0)

    # Parse titles — handle both JSON array and JSON object with array value
    try:
        parsed = json.loads(comp1.choices[0].message.content)
        if isinstance(parsed, list):
            titles = [str(t).strip() for t in parsed if t]
        elif isinstance(parsed, dict):
            # Model returned {"chapters": [...]} or {"titles": [...]} — extract first array
            for v in parsed.values():
                if isinstance(v, list):
                    titles = [str(t).strip() for t in v if t]
                    break
            if not titles:
                # Dict with string values — use keys as titles
                titles = [str(k).strip() for k in parsed.keys()]
    except json.JSONDecodeError:
        logger.error("Phase 1 JSON parse failed — falling back to line split")
        titles = [l.strip().strip('"').strip("- ") for l in comp1.choices[0].message.content.splitlines() if l.strip()]

    titles = titles[:hi_ch]  # cap at upper bound
    logger.info("Phase 1 complete: %d titles generated", len(titles))

    # ── PHASE 2: Generate descriptions for each title ─────────────────────────
    # Single call: pass all titles, get back {title: description} JSON
    desc_system = (
        "You are an expert book editor. You receive a list of chapter titles. "
        "For EACH title, write a 1–2 sentence description naming the specific sub-topics, "
        "concepts, mechanisms, or case studies that chapter will cover. "
        "Output ONLY a valid JSON object: keys are the exact titles, values are description strings. "
        "Keep ALL titles — do not remove or merge any."
    )
    titles_list_str = "\n".join(f"{i+1}. {t}" for i, t in enumerate(titles))
    desc_user = (
        f"Book subject: {subject}\n"
        f"{lang_instr}\n\n"
        f"Chapter titles:\n{titles_list_str}\n\n"
        "Generate a SPECIFIC description for each chapter. "
        "Each description should name concrete sub-topics (not vague overviews). "
        "Return JSON with all titles as keys."
    ).strip()

    logger.info("Phase 2: generating descriptions for %d titles", len(titles))
    desc_max_tokens = min(4096, len(titles) * 100 + 300)

    for attempt in range(4):
        try:
            comp2 = client.chat.completions.create(
                model=params.model,
                messages=[
                    {"role": "system", "content": desc_system},
                    {"role": "user", "content": desc_user},
                ],
                temperature=max(0.0, min(0.3, params.temperature)),
                max_tokens=desc_max_tokens,
                top_p=params.top_p,
                stream=False,
                response_format={"type": "json_object"},
            )
            break
        except Exception as e:
            if not _should_retry(e) or attempt == 3:
                # If Phase 2 fails entirely, build structure with titles only
                logger.warning("Phase 2 failed (%s) — using titles without descriptions", e)
                comp2 = None
                break
            time.sleep(_retry_delay(attempt))

    structure: Dict[str, Any] = {}

    if comp2:
        usage2 = comp2.usage
        total_input_tokens += getattr(usage2, "prompt_tokens", 0) or 0
        total_output_tokens += getattr(usage2, "completion_tokens", 0) or 0
        total_time += (getattr(usage2, "prompt_time", 0) or 0) + (getattr(usage2, "completion_time", 0) or 0)

        try:
            desc_parsed = json.loads(comp2.choices[0].message.content)
            if isinstance(desc_parsed, dict):
                structure = desc_parsed
        except json.JSONDecodeError:
            logger.warning("Phase 2 JSON parse failed — using titles without descriptions")

    # Ensure all titles are in structure (Phase 2 may have missed some)
    for t in titles:
        if t not in structure:
            structure[t] = f"Részletes fejezet: {t}"

    # If Phase 2 returned extra keys not in titles, drop them
    valid_titles_set = set(titles)
    structure = {k: v for k, v in structure.items() if k in valid_titles_set}

    # Reorder to match Phase 1 order
    ordered: Dict[str, Any] = {}
    for t in titles:
        if t in structure:
            ordered[t] = structure[t]
    structure = ordered

    logger.info("Phase 2 complete: %d chapters with descriptions", len(structure))

    # ── PHASE 3: Cleanup ──────────────────────────────────────────────────────
    try:
        structure = _strip_intro_conclusion(structure, params.include_intro, params.include_conclusion)
        structure = _dedupe_titles(structure)
    except Exception:
        pass

    # Enforce maximum
    effective_max = min(MAX_SECTIONS, num_ch + 5)
    try:
        structure = _limit_leaves(structure, effective_max)
    except Exception:
        pass

    # Ensure minimum
    try:
        structure = _ensure_min_leaves(structure, MIN_SECTIONS, subject)
    except Exception:
        pass

    final_count = len(_flatten_structure(structure))
    logger.info("Final structure: %d chapters (requested %d)", final_count, num_ch)

    statistics = GenerationStatistics(
        input_time=total_time / 2,
        output_time=total_time / 2,
        input_tokens=total_input_tokens,
        output_tokens=total_output_tokens,
        total_time=total_time,
        model_name=params.model,
    )

    stats_dict: Dict[str, Any] = {
        "model_name": statistics.model_name,
        "input_time": statistics.input_time,
        "output_time": statistics.output_time,
        "input_tokens": statistics.input_tokens,
        "output_tokens": statistics.output_tokens,
        "total_time": statistics.total_time,
    }

    return stats_dict, structure


def iter_sections_stream(
    structure: Dict[str, Any],
    params: SectionParams,
    is_cancelled: Optional[Callable[[], bool]] = None,
    client=None,
    start_index: int = 0,
    count: Optional[int] = None,
    mcp_config=None,  # Optional[List[MCPConfig]]
) -> Iterator[Dict[str, Any]]:
    """
    Yields NDJSON events as dicts: section_start, token, stats, section_end, done
    Adds global outline and prev/next context to improve cross-chapter cohesion.
    """
    outline = _flatten_structure(structure)
    outline_summary = _outline_summary(structure)

    def stream_one(
        idx: int,
        item: dict[str, Any],
        throttler: TpmThrottler,
        ltm: LongTermMemory,
        stm: ShortTermMemory,
    ) -> Iterator[Dict[str, Any]]:
        title: str = item["title"]
        section_prompt: str = item["prompt"]
        prev_item = outline[idx - 1] if idx > 0 else None
        next_item = outline[idx + 1] if idx + 1 < len(outline) else None

        lang_instr = _language_instruction(params.language)
        style_instr = _style_instruction(params.style, params.reading_level)
        extra_txt = (params.extra_instructions or "").strip()

        prev_ctx = f"Previous chapter: {prev_item['title']}\n" if prev_item else ""
        next_ctx = f"Next chapter: {next_item['title']}\n" if next_item else ""

        # MCP per-section (only fetched once, reused across sub-sections)
        mcp_snippet: str = ""
        if mcp_config:
            try:
                mcp_snippet = _mcp_multi(mcp_config, f"{title}: {section_prompt}", "per_section")
                if mcp_snippet:
                    logger.info("MCP per-section context for '%s' (%d chars)", title, len(mcp_snippet))
            except Exception as exc:
                logger.warning("MCP per-section call failed for '%s' (non-fatal): %s", title, exc)

        # Sub-section planning
        target_len = params.target_length or 1200
        n_subs = _n_subsections(target_len)
        words_per_sub = max(400, target_len // n_subs)
        plans = _plan_subsections(title, n_subs, words_per_sub)
        logger.info("Chapter '%s' → %d sub-section(s), ~%d words each", title, n_subs, words_per_sub)

        # Quality context derived from whitepaper structural analysis
        # Full block for opening sub-section; compact reminder for subsequent ones.
        _quality_full = build_quality_context_block(
            style=params.style,
            include_anatomy=True,
            include_paragraphs=True,
            include_headings=True,
            include_evidence=True,
            include_transitions=True,
            include_chapter_anatomy=True,
        )

        # Base system prompt — same for every sub-section
        system_text = (
            "You are an expert non-fiction book author. "
            "You are writing one segment of a chapter; the segments will be joined seamlessly into a single chapter. "
            "\n\nWriting quality standards (follow strictly):\n"
            "- SHOW, don't tell: illustrate every claim with a concrete example, case study, statistic, or analogy.\n"
            "- Every H2 section must contain at least 3 substantive paragraphs — no single-paragraph sections.\n"
            "- Each paragraph must develop ONE idea fully (topic sentence → explanation → evidence → implication).\n"
            "- Use specific numbers, names, dates, and mechanisms — avoid vague generalisations.\n"
            "- Vary sentence length; mix short punchy statements with longer analytical sentences.\n"
            "- Do NOT open a paragraph with 'In conclusion', 'In summary', 'It is important to note', or similar fillers.\n"
            "- Maintain consistent terminology with the rest of the book (see outline and memory context).\n"
            "- Stay strictly on the chapter topic — do NOT introduce material covered in other chapters.\n"
            "\nFormatting:\n"
            "- Valid Markdown only (no raw HTML, no unclosed code fences).\n"
            "- Use H2 (##) and H3 (###) headings to structure content; never deeper than H3.\n"
            "- Prefer rich paragraphs; bullet lists only for genuinely enumerable items (4+ items).\n"
            "- Tables only when comparative data has clear row/column structure.\n"
            f"\n{lang_instr} {style_instr}"
        ).strip()

        # Reset short-term memory at start of each chapter
        stm.reset()
        chapter_content_parts: list[str] = []

        if is_cancelled and is_cancelled():
            return

        yield {"type": "section_start", "title": title}

        c = client or groq_client
        try:
            c = c.with_options(timeout=60)
        except Exception:
            pass

        for sub_idx, plan in enumerate(plans):
            if is_cancelled and is_cancelled():
                break

            # TPM check between sub-sections (skip before first)
            if sub_idx > 0:
                sub_pending: list[float] = []
                throttler.wait_if_needed(
                    needed_tokens=plan["max_tokens"],
                    yield_cb=lambda w: sub_pending.append(w),
                    is_cancelled=is_cancelled,
                )
                for w in sub_pending:
                    yield {"type": "rate_limit_wait", "title": title,
                           "wait": round(w, 1), "message": "TPM budget low — waiting for reset"}

            # Build user message for this sub-section
            # Order: task first (highest attention) → chapter info → memory → context → extras
            user_parts: list[str] = []

            # ① Task instruction — first so the model knows its goal immediately
            user_parts.append(f"## TASK\n{plan['instruction']}\n\n")

            # ② Chapter info
            user_parts.append(
                f"## CHAPTER\n"
                f"Title: {title}\n"
                f"Description (content scope): {section_prompt}\n\n"
            )

            # ③ Short-term memory — seamless continuation within chapter
            stm_ctx = stm.context()
            if stm_ctx:
                user_parts.append(f"## CONTINUATION CONTEXT\n{stm_ctx}\n\n")

            # ④ Long-term memory — cross-chapter consistency
            ltm_ctx = ltm.context()
            if ltm_ctx:
                user_parts.append(f"## BOOK CONTEXT\n{ltm_ctx}\n")

            # ⑤ Structural context (outline + adjacent) — only for first sub-section to reduce noise
            if plan["is_first"]:
                user_parts.append(f"Book outline (all chapters):\n{outline_summary}\n\n")
                if prev_ctx or next_ctx:
                    user_parts.append(f"Adjacent chapters:\n{prev_ctx}{next_ctx}\n")

            # ⑥ MCP context only on first sub-section
            if sub_idx == 0 and mcp_snippet:
                user_parts.append(
                    f"## EXTERNAL RESEARCH CONTEXT\n"
                    f"(Use facts, data, and examples from this to enrich the chapter.)\n"
                    f"<mcp_context>\n{mcp_snippet}\n</mcp_context>\n\n"
                )

            if extra_txt:
                user_parts.append(f"## ADDITIONAL AUTHOR INSTRUCTIONS\n{extra_txt}\n\n")

            # ⑦ Quality context — full guide for opening, compact reminder for middle/closing
            if plan["is_first"]:
                user_parts.append(f"## QUALITY WRITING REFERENCE\n{_quality_full}\n\n")
            else:
                user_parts.append(f"## QUALITY REMINDER\n{COMPACT_QUALITY_REMINDER}\n\n")

            # ⑧ Heading rule
            user_parts.append("## OUTPUT RULES\n")
            user_parts.append("- Output ONLY the chapter text in valid Markdown. No meta-comments, no preamble.\n")
            if plan["is_first"]:
                user_parts.append(f"- FIRST LINE must be: # {title}\n")
            else:
                user_parts.append(
                    "- Do NOT write an H1 heading. Start directly with ## (H2).\n"
                    "- Do NOT recap or summarise previous content — write new content only.\n"
                )

            user_text = "".join(user_parts)
            messages = [
                {"role": "system", "content": system_text},
                {"role": "user", "content": user_text},
            ]

            # Stream this sub-section with retries
            last_err: Optional[Exception] = None
            stream = None
            for attempt in range(4):
                if is_cancelled and is_cancelled():
                    return
                try:
                    stream = c.chat.completions.create(
                        model=params.model,
                        messages=messages,
                        temperature=params.temperature,
                        max_tokens=plan["max_tokens"],
                        top_p=params.top_p,
                        stream=True,
                        stop=None,
                    )
                    throttler.update_from_stream(stream)
                    last_err = None
                    break
                except Exception as e:
                    last_err = e
                    if not ("429" in str(e) or "rate limit" in str(e).lower() or "timeout" in str(e).lower()) or attempt == 3:
                        break
                    wait_s = min(60, (2 ** attempt) + 1.0)
                    yield {"type": "rate_limit_wait", "title": title, "wait": round(wait_s, 1), "message": str(e)}
                    logger.warning("Sub '%s'[%d] rate limit, waiting %.1fs (attempt %d)", title, sub_idx, wait_s, attempt + 1)
                    end = time.time() + wait_s
                    while time.time() < end:
                        if is_cancelled and is_cancelled():
                            return
                        time.sleep(0.1)
            if last_err is not None and stream is None:
                raise last_err

            sub_content_parts: list[str] = []
            for chunk in stream:
                if is_cancelled and is_cancelled():
                    break
                try:
                    tokens = chunk.choices[0].delta.content
                except Exception:
                    tokens = None
                if tokens:
                    yield {"type": "token", "title": title, "delta": tokens}
                    sub_content_parts.append(tokens)

                # stats (final chunk)
                xg = getattr(chunk, "x_groq", None)
                if not xg:
                    continue
                usage = xg.get("usage") if isinstance(xg, dict) else getattr(xg, "usage", None)
                if not usage:
                    continue
                get_val = usage.get if isinstance(usage, dict) else (lambda k, d=None: getattr(usage, k, d))
                yield {"type": "stats", "title": title, "statistics": {
                    "model_name": params.model,
                    "input_time": get_val("prompt_time", 0) or 0,
                    "output_time": get_val("completion_time", 0) or 0,
                    "input_tokens": get_val("prompt_tokens", 0) or 0,
                    "output_tokens": get_val("completion_tokens", 0) or 0,
                    "total_time": get_val("total_time", 0) or 0,
                }}

            # Update short-term memory with tail of this sub-section
            sub_content = "".join(sub_content_parts)
            stm.update(sub_content)
            chapter_content_parts.append(sub_content)

        # After all sub-sections, register this chapter in long-term memory
        if not (is_cancelled and is_cancelled()):
            ltm.add(title, "".join(chapter_content_parts))

        if is_cancelled and is_cancelled():
            return
        yield {"type": "section_end", "title": title}

    start = max(0, int(start_index or 0))
    end = len(outline) if count in (None, 0, False) else min(len(outline), start + int(count))
    start = min(start, len(outline))
    end = max(start, end)

    throttler = TpmThrottler(params.model)
    ltm = LongTermMemory()   # shared across all chapters in this generation run
    stm = ShortTermMemory()  # reset per chapter inside stream_one

    for idx in range(start, end):
        item = outline[idx]
        if is_cancelled and is_cancelled():
            break

        # TPM-aware throttling before each chapter (not before the first)
        if idx > start:
            chapter_pending: list[float] = []
            # Estimate total tokens for ALL sub-sections in this chapter
            target_len = params.target_length or 1200
            n_subs_est = _n_subsections(target_len)
            plans_est = _plan_subsections(item.get("title", ""), n_subs_est, max(400, target_len // n_subs_est))
            sub_tokens_est = sum(p["max_tokens"] for p in plans_est)
            throttler.wait_if_needed(
                needed_tokens=sub_tokens_est,
                yield_cb=lambda w: chapter_pending.append(w),
                is_cancelled=is_cancelled,
            )
            for w in chapter_pending:
                yield {"type": "rate_limit_wait", "title": item.get("title", ""), "wait": round(w, 1),
                       "message": "TPM budget low — waiting for rate-limit window to reset"}

        # Optional fixed pacing
        if (idx - start) > 0 and SECTION_PACING_S > 0:
            yield {"type": "rate_limit_wait", "title": item.get("title", ""), "wait": round(SECTION_PACING_S, 2), "message": "pacing"}
            pace_end = time.time() + SECTION_PACING_S
            while time.time() < pace_end:
                if is_cancelled and is_cancelled():
                    break
                time.sleep(0.05)

        yield from stream_one(idx, item, throttler, ltm, stm)

    if is_cancelled and is_cancelled():
        yield {"type": "aborted"}
    else:
        yield {"type": "done"}
