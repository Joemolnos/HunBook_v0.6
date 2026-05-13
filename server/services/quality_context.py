"""
quality_context.py — Structural writing templates derived from whitepaper analysis.

Sources analysed (2026-05-13):
  1. "Attention Is All You Need" — Vaswani et al. (2017), academic AI paper
     Structure: numbered H2 (1–7) → numbered H3 (3.1, 3.2…) → bold H4 labels
     Patterns: abstract first; intro = problem→prior work→contribution→roadmap;
               every claim immediately supported by equation or empirical metric;
               tables for method comparison; careful forward-references.

  2. "How People Read Online" — Nielsen Norman Group (eyetracking report)
     Structure: one-sentence summary; ToC; H2 as questions/claims; H3 subdivisions
     Patterns: each H3 = finding → data (N, year) → implication → guideline;
               bullet lists only for 4+ enumerable items; no passive voice.

  3. "What Is ChatGPT Doing and Why Does It Work?" — Stephen Wolfram (long-form essay)
     Structure: 15 H2 chapters, no H3, progressive depth
     Patterns: each H2 opens with a thought-experiment or concrete scenario;
               conversational bridges ("So let's say…", "OK, but…");
               specific numbers in EVERY paragraph ("40,000 words", "175 billion parameters");
               no chapter summaries — each section ends by hinting at the next question.

Usage:
    from services.quality_context import (
        SECTION_ANATOMY_GUIDE,
        PARAGRAPH_STRUCTURE_GUIDE,
        HEADING_TITLE_PATTERNS,
        EVIDENCE_VOCABULARY_GUIDE,
        TRANSITION_GUIDE,
        build_quality_context_block,
    )
    Inject ``build_quality_context_block(style)`` into the section-generation system prompt.
"""

from __future__ import annotations


# ── 1. Section anatomy ────────────────────────────────────────────────────────

SECTION_ANATOMY_GUIDE = """\
## Reference: How high-quality non-fiction sections are structured

Every H2 section follows this four-part anatomy:

HOOK (1–2 sentences)
  Open with a concrete scenario, striking statistic, or provocative question that
  makes the reader need to know the answer. Never open with a vague topic sentence
  like "This section discusses X."
  Good: "In 2019, a single datacenter consumed more electricity than 50,000 homes —
         and the culprit was not the servers, but the cooling system."
  Bad:  "This section provides an overview of data center energy consumption."

CONTEXT / MECHANISM (2–4 paragraphs)
  Explain the underlying mechanism, history, or concept with precision.
  Every claim must be grounded: use a named example, a date, a number, or a study.
  Academic style: cite mechanism → cite evidence → interpret.
  Essay style: analogy first → then technical term → then implication.

EVIDENCE / CASE STUDY (1–3 paragraphs)
  Illustrate with a real-world case, experiment, or comparative data.
  Ideal: a before/after, a failure/success pair, or a counterintuitive result.
  Use a table only if comparing ≥3 named items across ≥2 dimensions.

IMPLICATION / BRIDGE (1 paragraph)
  Close the section by drawing out the consequence of what was shown —
  not a summary ("we saw that…") but an implication ("this means that…")
  or a forward bridge ("the mechanism above is what makes the next problem possible").
"""


# ── 2. Paragraph structure ────────────────────────────────────────────────────

PARAGRAPH_STRUCTURE_GUIDE = """\
## Reference: Paragraph-level writing patterns from analysed whitepapers

The TIC pattern (used in every paragraph of quality non-fiction):
  T — Topic sentence:    One clear claim in plain language.
  I — Illustration:      A specific, named example, statistic, or analogy.
  C — Consequence:       Why it matters; what it implies; what question it raises.

Sentence-length rhythm (observed in all three sources):
  • Short sentence for impact (≤ 10 words).
  • Medium analytical sentence to develop the idea (15–25 words).
  • Longer synthesis sentence that connects to the broader argument (25–40 words).
  • Never three consecutive sentences of the same length.

Specificity rules:
  • Replace "many researchers" → name one: "Bahdanau et al. (2015)"
  • Replace "significantly faster" → quantify: "3.5× faster on WMT14 En-Fr"
  • Replace "some cases" → give an instance: "as in Google's 2023 deployment"
  • Replace "recent years" → date it: "since 2017" or "by 2022"

Forbidden paragraph openers (these signal low-quality AI text):
  "It is important to note…"
  "In conclusion…" / "In summary…" / "To summarise…"
  "This section will discuss…"
  "As mentioned earlier…" (unless immediately followed by a new angle)
  "There are many factors…"
  "It should be noted that…"
"""


# ── 3. Heading title patterns ─────────────────────────────────────────────────

HEADING_TITLE_PATTERNS = """\
## Reference: H2/H3 heading title formulas from quality whitepapers

QUESTION titles (create curiosity — best for analytical chapters):
  "Why Does X Fail at Scale?"
  "What Happens When Assumptions Break Down?"
  "Is X Always Better Than Y?"

MECHANISM titles (precise, informative — best for technical chapters):
  "Scaled Dot-Product Attention"
  "The Encoder-Decoder Architecture"
  "Residual Connections and Layer Normalisation"

CLAIM/CONTRAST titles (provocative — best for argument-driven chapters):
  "Attention Is All You Need"
  "It's Just Adding One Word at a Time"
  "Scanning, Not Reading: What the Data Shows"

NUMBERED-INSIGHT titles (best for practical or listicle sections):
  "Three Properties of Self-Attention"
  "Two Failure Modes of Recurrent Networks"

Rules:
  • H2 titles: 3–7 words, no terminal period, sentence-case.
  • H3 titles: 2–5 words, name the specific sub-concept being explained.
  • Avoid: "Overview of X", "Introduction to X", "Discussion of X".
"""


# ── 4. Evidence and specificity vocabulary ────────────────────────────────────

EVIDENCE_VOCABULARY_GUIDE = """\
## Reference: Evidence framing vocabulary from quality whitepapers

Quantitative grounding:
  "In a corpus of 750 hours of eyetracking data across 500 participants…"
  "The model achieves 28.4 BLEU — 2 points above the previous best ensemble."
  "With 175 billion parameters, the network…"
  "Across 40,000 common English words, the probability distribution…"

Comparative framing:
  "Whereas recurrent models require O(n) sequential steps, self-attention uses O(1)."
  "While the 2006 study found F-pattern dominance, the 2019 data shows pinball patterns on SERPs."
  "Unlike additive attention, dot-product attention scales with matrix multiplication…"

Causal mechanism framing:
  "The reason is that dot products grow large in magnitude as d_k increases, pushing…"
  "This matters because sequential dependencies in RNNs prevent GPU parallelisation during training."
  "The underlying cause is human information-seeking behaviour, which technology cannot change."

Hedged uncertainty (academic and research writing):
  "The evidence suggests, though does not prove, that…"
  "We hypothesise that this absence is because…"
  "It remains unclear whether… — future work should test…"
"""


# ── 5. Transition patterns ────────────────────────────────────────────────────

TRANSITION_GUIDE = """\
## Reference: Section-to-section transition patterns

Forward bridge (used to open next section by referencing current one):
  "This limitation is precisely what motivates the approach in the next section."
  "With this mechanism in place, we can now ask a more subtle question…"
  "The result above only holds under one critical assumption — which the next section examines."

Contrast bridge (used when next section challenges the current view):
  "So far the picture looks clean. But there is a complication."
  "This works well in theory. The practice reveals a different story."

Implication closer (for section endings that don't lead to next section):
  "The practical consequence is that engineers can now… without sacrificing…"
  "This finding has a non-obvious implication: X is not a property of Y, but of Z."
  "What this means for practitioners is straightforward: always check X before assuming Y."

Synthesis closer (for closing segments of a chapter):
  "Taken together, these three mechanisms explain why X outperforms Y in nearly every benchmark."
  "The common thread is not performance, but a shift in how the system represents information."
  — NEVER use: "In conclusion, we have seen…" / "To summarise the above points…"
"""


# ── 6. Intro / body / conclusion chapter anatomy ─────────────────────────────

CHAPTER_ANATOMY = """\
## Reference: Chapter-level structure (from whitepaper analysis)

OPENING SEGMENT (first ~35% of chapter):
  • Hook: 1 striking fact, anecdote, or question (≤ 3 sentences).
  • Context: Establish why this chapter matters within the book's arc.
  • Scope: State explicitly what this chapter covers and (if useful) what it does NOT.
  • First major sub-topic: deep dive into the first H2 section with evidence and examples.

MIDDLE SEGMENT(S) (middle ~50%):
  • Each H2 section = one self-contained argument unit (see SECTION ANATOMY above).
  • Transitions between H2 sections use forward bridges or contrast bridges.
  • Include at least one table or comparison where two or more approaches are discussed.
  • Variety: alternate between theoretical explanation, empirical data, and real-world example.

CLOSING SEGMENT (final ~15%):
  • Synthesis paragraph: connect the chapter's key insights — reveal the pattern that ties them.
  • Open question or implication: end with a forward-looking statement or unresolved tension.
  • Bridge to next chapter (optional, 1 sentence): "This sets the stage for…"
  • NEVER write a bullet-point summary of what was covered ("In this chapter we learned…").
"""


# ── 7. Style-specific structural advice ──────────────────────────────────────

_STYLE_STRUCTURE_ADVICE: dict[str, str] = {
    "akadémikus": (
        "Academic structure: number all H2 sections (1, 2, 3…) and H3 subsections (2.1, 2.2…). "
        "Every empirical claim requires a source attribution or mechanism explanation. "
        "Use hedged language ('suggests', 'indicates', 'we hypothesise'). "
        "Tables are preferred over prose for comparative data. "
        "No rhetorical questions in headers — use declarative mechanism titles."
    ),
    "közérthető": (
        "Popular-science structure: open every H2 section with a concrete human story or relatable scenario. "
        "Technical terms must be immediately defined in plain language after first use. "
        "Use rhetorical questions as H2 titles ('Why Does This Matter?'). "
        "Bullet lists are acceptable but must follow a plain-language lead-in sentence. "
        "Avoid tables; use descriptive comparisons instead ('twice as fast', 'half the cost')."
    ),
    "narratív": (
        "Narrative structure: each H2 section opens with a scene, character, or event. "
        "Facts and mechanisms are revealed through the story, not before it. "
        "Use anaphora and short punchy sentences for rhythm. "
        "Avoid all bullet lists — every list item must become a full sentence or paragraph. "
        "End each section with a human consequence, not a technical conclusion."
    ),
    "technikai": (
        "Technical structure: H2 titles name the specific component, API, or procedure. "
        "Every subsection should contain: definition → parameters/conditions → example → edge cases. "
        "Use numbered lists for multi-step procedures (≥ 3 steps). "
        "Tables are strongly preferred for option/parameter comparison. "
        "End sections with a 'Notes / Caveats' H3 if there are known limitations."
    ),
}


def get_style_structure_advice(style: str | None) -> str:
    """Return style-specific structural advice for the given writing style key."""
    if not style:
        return ""
    key = (style or "").lower().strip()
    return _STYLE_STRUCTURE_ADVICE.get(key, "")


# ── 8. Composite builder ──────────────────────────────────────────────────────

def build_quality_context_block(
    style: str | None = None,
    include_anatomy: bool = True,
    include_paragraphs: bool = True,
    include_headings: bool = True,
    include_evidence: bool = True,
    include_transitions: bool = True,
    include_chapter_anatomy: bool = False,
) -> str:
    """
    Build a compact quality-context block suitable for injection into the LLM system prompt.

    Args:
        style: Writing style key ('akadémikus', 'közérthető', 'narratív', 'technikai').
        include_anatomy: Include the section-level anatomy guide.
        include_paragraphs: Include paragraph structure guide.
        include_headings: Include heading title patterns.
        include_evidence: Include evidence vocabulary guide.
        include_transitions: Include transition patterns.
        include_chapter_anatomy: Include chapter-level anatomy (for first/last sub-sections).

    Returns:
        A multi-line string ready for insertion into the system prompt.
    """
    parts: list[str] = [
        "─────────────────────────────────────────────────────────────────────────────",
        "WRITING QUALITY REFERENCE (derived from analysis of high-quality whitepapers)",
        "─────────────────────────────────────────────────────────────────────────────",
    ]

    if include_anatomy:
        parts.append(SECTION_ANATOMY_GUIDE)

    if include_paragraphs:
        parts.append(PARAGRAPH_STRUCTURE_GUIDE)

    if include_headings:
        parts.append(HEADING_TITLE_PATTERNS)

    if include_evidence:
        parts.append(EVIDENCE_VOCABULARY_GUIDE)

    if include_transitions:
        parts.append(TRANSITION_GUIDE)

    if include_chapter_anatomy:
        parts.append(CHAPTER_ANATOMY)

    style_advice = get_style_structure_advice(style)
    if style_advice:
        parts.append(
            f"## Style-specific structural advice ({style})\n{style_advice}"
        )

    parts.append(
        "─────────────────────────────────────────────────────────────────────────────"
    )

    return "\n\n".join(parts)


# ── 9. Compact variant (for per-sub-section injection to save tokens) ─────────

COMPACT_QUALITY_REMINDER = """\
Writing quality checklist (MUST follow):
• HOOK: Open every H2 section with a specific example, number, or scenario — not a topic sentence.
• TIC paragraphs: Topic claim → Illustration (named, quantified) → Consequence.
• SPECIFICITY: Replace "many", "some", "recent" with exact numbers, names, dates.
• RHYTHM: Short punchy sentence. Medium analytical sentence to expand. Longer synthesis sentence.
• TRANSITIONS: End sections with an implication or forward bridge — never a summary.
• FORBIDDEN openers: "It is important to note", "In conclusion", "This section discusses".\
"""
