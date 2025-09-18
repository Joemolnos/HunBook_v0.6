from __future__ import annotations
from typing import Any, Dict, Iterator, Tuple, Callable, Optional
import json
import time
import logging
import os

from config import groq_client
from stats import GenerationStatistics
from ..schemas import StructureParams, SectionParams


SYSTEM_STRUCTURE = (
    "Write in JSON format only. Keys are section titles, values are either descriptions (string) "
    "or nested objects for subsections. Ensure a coherent, logically ordered outline strictly relevant to the given subject. "
    "Avoid unrelated tangents, duplication across sections, and redundant scope. Maintain consistent terminology throughout. "
    "Do not include any introduction/foreword/author's note/summary unless explicitly requested."
)

logger = logging.getLogger(__name__)
SECTION_PACING_S = float(os.getenv("SECTION_PACING_S", "0"))  # optional pacing between sections


def _language_instruction(language: str) -> str:
    if not language:
        return ""
    return f"Write all content in { 'Hungarian' if language.lower().startswith('hu') else language }."


def _style_instruction(style: str | None, reading_level: str | None) -> str:
    parts = []
    if style:
        parts.append(f"Use a {style} style.")
    if reading_level:
        parts.append(f"Target reading level: {reading_level}.")
    return " ".join(parts)


def _length_instruction(target_length: int | None) -> str:
    if target_length:
        return f"Aim for approximately {target_length} tokens of detailed, well-structured content."
    return ""


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
    try:
        return filt(sections or {})
    except Exception:
        return sections


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
    """Ask the LLM to prune/merge irrelevant items and enforce coherence. Returns refined JSON or raises."""
    editor_system = (
        "You are an expert book editor. You will receive a DRAFT JSON outline for a book. "
        "Revise it to ensure strict relevance to the SUBJECT, remove or merge any off-topic or redundant sections, "
        "and maintain consistent terminology. Depth must not exceed the requested depth. Preserve only sections that directly support the subject. "
        "Output JSON only as a mapping: titles -> string (description) or nested objects for subsections."
    )
    user_text = (
        f"SUBJECT (in Hungarian if applicable):\n{subject}\n\n"
        f"REQUESTED DEPTH: {params.depth}\n"
        + (f"ADDITIONAL USER INSTRUCTIONS (optional):\n{extra_txt}\n\n" if extra_txt else "")
        + "DRAFT OUTLINE (JSON):\n" + json.dumps(draft, ensure_ascii=False)
    )
    c = client or groq_client
    # Prefer a bounded timeout to avoid indefinite stalls
    try:
        c = c.with_options(timeout=60)
    except Exception:
        pass
    completion = c.chat.completions.create(
        model=params.model,
        messages=[{"role": "system", "content": editor_system}, {"role": "user", "content": user_text}],
        temperature=max(0.0, min(0.4, float(params.temperature or 0.3))),  # keep this conservative
        max_tokens=params.max_tokens,
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


def generate_book_structure_service(subject: str, params: StructureParams, client=None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Returns (statistics_dict, structure_dict)
    """
    # Build prompt with depth and intro/conclusion preference
    intro_instr = (
        "Include an introduction and conclusion sections." if params.include_intro or params.include_conclusion
        else "Omit introduction and conclusion sections (foreword, author's note, summary)."
    )
    depth_instr = f"Create up to {params.depth} levels of sections."
    lang_instr = _language_instruction(params.language)

    extra_txt = (params.extra_instructions or "").strip()

    messages = [
        {"role": "system", "content": SYSTEM_STRUCTURE},
        {
            "role": "user",
            "content": (
                f"{lang_instr} {intro_instr} {depth_instr}\n\n"
                + (f"Additional user instructions (optional):\n<extra>\n{extra_txt}\n</extra>\n\n" if extra_txt else "")
                + f"Write a comprehensive structure for a long (>300 page) book on the following subject:\n\n<subject>{subject}</subject>"
            ).strip(),
        },
    ]

    # Try strict JSON mode first; some models may return 400 json_validate_failed.
    client = client or groq_client
    # Prefer a bounded timeout to avoid indefinite stalls
    try:
        client = client.with_options(timeout=60)
    except Exception:
        pass
    def _should_retry(err: Exception) -> bool:
        msg = str(err)
        low = msg.lower()
        return ("429" in msg) or ("rate limit" in low) or ("timeout" in low) or ("temporarily unavailable" in low)

    def _retry_delay(attempt: int, err: Exception) -> float:
        # Exponential backoff with jitter
        base = min(2 ** attempt, 8)  # 1,2,4,8
        return base + (0.5 * (attempt + 1))

    # First try strict JSON response format, with retries on 429/timeout
    last_err: Optional[Exception] = None
    for attempt in range(4):
        try:
            completion = client.chat.completions.create(
                model=params.model,
                messages=messages,
                temperature=params.temperature,
                max_tokens=params.max_tokens,
                top_p=params.top_p,
                stream=False,
                response_format={"type": "json_object"},
                stop=None,
            )
            last_err = None
            break
        except Exception as e:
            last_err = e
            if not _should_retry(e) or attempt == 3:
                break
            wait_s = _retry_delay(attempt, e)
            logger.warning("Structure call rate-limited/timeout, retrying in %.1fs (attempt %d)", wait_s, attempt + 1)
            time.sleep(wait_s)
    if last_err is not None and 'completion' not in locals():
        # Fallback without JSON enforcement (also with retries)
        for attempt in range(4):
            try:
                completion = client.chat.completions.create(
                    model=params.model,
                    messages=messages,
                    temperature=params.temperature,
                    max_tokens=params.max_tokens,
                    top_p=params.top_p,
                    stream=False,
                    stop=None,
                )
                last_err = None
                break
            except Exception as e:
                last_err = e
                if not _should_retry(e) or attempt == 3:
                    break
                wait_s = _retry_delay(attempt, e)
                logger.warning("Structure fallback call rate-limited/timeout, retrying in %.1fs (attempt %d)", wait_s, attempt + 1)
                time.sleep(wait_s)
    if last_err is not None and 'completion' not in locals():
        raise last_err

    usage = completion.usage
    statistics = GenerationStatistics(
        input_time=getattr(usage, "prompt_time", 0) or 0,
        output_time=getattr(usage, "completion_time", 0) or 0,
        input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        output_tokens=getattr(usage, "completion_tokens", 0) or 0,
        total_time=getattr(usage, "total_time", 0) or 0,
        model_name=params.model,
    )

    content = completion.choices[0].message.content
    try:
        structure = json.loads(content)
    except json.JSONDecodeError:
        # Fallback: wrap as a single section
        structure = {"Book": content}

    # Rule-based cleanup: remove intro/conclusion unless requested; dedupe titles
    try:
        structure = _strip_intro_conclusion(structure, params.include_intro, params.include_conclusion)
        structure = _dedupe_titles(structure)
    except Exception:
        pass

    # Coherence refinement pass via LLM; fallback to draft on any failure
    try:
        structure = _refine_structure_for_coherence(subject, extra_txt, structure, params, client=client)
    except Exception:
        # keep original structure if refine fails
        pass

    # Serialize statistics to dict compatible with API schema
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
) -> Iterator[Dict[str, Any]]:
    """
    Yields NDJSON events as dicts: section_start, token, stats, section_end, done
    Adds global outline and prev/next context to improve cross-chapter cohesion.
    """
    outline = _flatten_structure(structure)
    outline_summary = _outline_summary(structure)

    def stream_one(idx: int, item: dict[str, Any]) -> Iterator[Dict[str, Any]]:
        title: str = item["title"]
        section_prompt: str = item["prompt"]
        prev_item = outline[idx - 1] if idx > 0 else None
        next_item = outline[idx + 1] if idx + 1 < len(outline) else None

        lang_instr = _language_instruction(params.language)
        style_instr = _style_instruction(params.style, params.reading_level)
        len_instr = _length_instruction(params.target_length)

        prev_ctx = f"Previous: {prev_item['title']} — {prev_item['prompt']}\n" if prev_item else ""
        next_ctx = f"Next: {next_item['title']} — {next_item['prompt']}\n" if next_item else ""

        extra_txt = (params.extra_instructions or "").strip()

        system_text = (
            "You are an expert book author. Generate a long, comprehensive, structured chapter for the provided section. "
            "Maintain strong cohesion with the overall outline and adjacent chapters. Use consistent terminology, avoid redundancy, "
            "and do not introduce unrelated topics beyond the outline. Explicitly stay on-topic relative to the section description and the outline. "
            "Cross-reference other sections when appropriate. "
            f"{lang_instr} {style_instr} {len_instr}"
        ).strip()

        parts = [
            f"Global Outline (compact):\n{outline_summary}\n\n",
            f"Adjacent Context:\n{prev_ctx}{next_ctx}\n",
            "Guidance: Ensure all content directly supports the section_title and remains consistent with the outline. Avoid tangents.\n\n",
        ]
        if extra_txt:
            parts.append(f"Additional user instructions (optional):\n{extra_txt}\n\n")
        parts.extend([
            "Write the chapter for the following section title and description:\n\n",
            f"<section_title>{title}</section_title>\n",
            f"<section_description>{section_prompt}</section_description>\n",
        ])
        user_text = "".join(parts)

        messages = [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text},
        ]

        # Early cancellation check before starting section
        if is_cancelled and is_cancelled():
            return

        yield {"type": "section_start", "title": title}

        c = client or groq_client
        try:
            # Keep streaming responsive: shorter read timeout prevents indefinite hangs on the last section
            c = c.with_options(timeout=30)
        except Exception:
            pass

        # Start stream with retries for 429/timeout
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
                    max_tokens=params.max_tokens,
                    top_p=params.top_p,
                    stream=True,
                    stop=None,
                )
                last_err = None
                break
            except Exception as e:
                last_err = e
                if not ("429" in str(e) or "rate limit" in str(e).lower() or "timeout" in str(e).lower()) or attempt == 3:
                    break
                wait_s = min(60, (2 ** attempt) + 1.0)
                # Surface wait info to client so UI can reflect backoff status
                yield {"type": "rate_limit_wait", "title": title, "wait": round(wait_s, 1), "message": str(e)}
                logger.warning("Section '%s' start hit rate limit/timeout, waiting %.1fs before retry (attempt %d)", title, wait_s, attempt + 1)
                # Backoff while still honoring cancellation
                end = time.time() + wait_s
                while time.time() < end:
                    if is_cancelled and is_cancelled():
                        return
                    time.sleep(0.1)
        if last_err is not None and stream is None:
            raise last_err

        for chunk in stream:
            # Cancellation in-flight
            if is_cancelled and is_cancelled():
                break
            # tokens
            try:
                tokens = chunk.choices[0].delta.content
            except Exception:
                tokens = None
            if tokens:
                yield {"type": "token", "title": title, "delta": tokens}

            # stats (final chunk metadata)
            xg = getattr(chunk, "x_groq", None)
            if not xg:
                continue
            usage = xg.get("usage") if isinstance(xg, dict) else getattr(xg, "usage", None)
            if not usage:
                continue
            get_val = usage.get if isinstance(usage, dict) else (lambda k, d=None: getattr(usage, k, d))
            stats = {
                "model_name": params.model,
                "input_time": get_val("prompt_time", 0) or 0,
                "output_time": get_val("completion_time", 0) or 0,
                "input_tokens": get_val("prompt_tokens", 0) or 0,
                "output_tokens": get_val("completion_tokens", 0) or 0,
                "total_time": get_val("total_time", 0) or 0,
            }
            yield {"type": "stats", "title": title, "statistics": stats}

        if is_cancelled and is_cancelled():
            # skip normal section_end to indicate aborted section
            return
        yield {"type": "section_end", "title": title}

    for idx, item in enumerate(outline):
        if is_cancelled and is_cancelled():
            break
        # Optional pacing to avoid bursting into rate limits
        if idx > 0 and SECTION_PACING_S > 0:
            yield {"type": "rate_limit_wait", "title": item.get("title", ""), "wait": round(SECTION_PACING_S, 2), "message": "pacing"}
            end = time.time() + SECTION_PACING_S
            while time.time() < end:
                if is_cancelled and is_cancelled():
                    break
                time.sleep(0.05)
        yield from stream_one(idx, item)

    if is_cancelled and is_cancelled():
        yield {"type": "aborted"}
    else:
        yield {"type": "done"}
