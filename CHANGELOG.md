# Changelog

## [0.7.0] — 2026-05-13

### Major: Multi-Phase Structure Generation

The entire book outline generation has been rewritten into a **3-phase pipeline** that reliably produces the exact number of chapters requested (3–50):

- **Phase 1** — Generate chapter titles only (JSON array, token-efficient)
- **Phase 2** — Generate specific descriptions for each title (separate LLM call)
- **Phase 3** — Cleanup, deduplication, and enforcement

Previously, a single large JSON generation would truncate at high chapter counts, silently producing 3 chapters instead of 30.

### Major: MCP Multi-Call Pipeline

Complete rewrite of `mcp_service.py` from single-tool-call to intelligent multi-step pipeline:

- **Server classification**: Auto-detects server type (context7 / wikipedia / web_search / generic) from URL and tool names
- **Query decomposition**: Splits each query into 2–3 targeted sub-queries (overview, examples, mechanisms)
- **Tool chaining**: Context7 uses `resolve-library-id → get-library-docs` sequential chain
- **Parallel execution**: Web search and generic servers run multiple queries via `asyncio.gather`
- **Result merging**: Jaccard-based deduplication, structured headers per result, 8000 char cap

### Major: Whitepaper-Based Quality Context

New `quality_context.py` module providing structural writing templates derived from analysis of:
- "Attention Is All You Need" (Vaswani et al.)
- "How People Read Online" (Nielsen Norman Group)
- "What Is ChatGPT Doing?" (Stephen Wolfram)

Templates include:
- **Section anatomy**: HOOK → CONTEXT → EVIDENCE → IMPLICATION
- **Paragraph structure**: TIC pattern (Topic → Illustration → Consequence)
- **Heading title patterns**: Question / Mechanism / Claim / Numbered-insight formulas
- **Evidence vocabulary**: Quantitative / Comparative / Causal / Hedged framing
- **Transition patterns**: Forward bridge / Contrast bridge / Synthesis closers
- **Style-specific advice**: Per writing style (akadémikus, közérthető, narratív, technikai)

Injected into LLM prompts: full guide for opening sub-section, compact reminder for middle/closing.

### Feature: Dynamic Chapter Count

- New `num_chapters` parameter (3–50, default 15) in `StructureParams` schema
- New "Fejezetek száma" slider in the UI
- `MAX_SECTIONS` raised from 25 to 50
- LLM prompt dynamically adjusts requested range based on user selection
- Frontend `effectiveMax` respects user's slider value

### Improved: Prompt Engineering (all LLM prompts)

- `SYSTEM_STRUCTURE` → dynamic function `_build_system_structure(n)` adapting to chapter count
- Section generation system prompt: explicit quality standards (show don't tell, TIC paragraphs, forbidden openers)
- Sub-section instructions: position indicators `[Segment 1/3]`, chapter description ties
- Style guides: detailed per-style writing instructions (akadémikus/közérthető/narratív/technikai)
- Reading level guides: általános/közép/egyetemi/szakértő with specific expectations
- User message reordering: TASK first → chapter info → STM → LTM → context → output rules

### Improved: Memory System

- **Long-Term Memory (LTM)**: Condensed summaries of past chapters for cross-chapter consistency
- **Short-Term Memory (STM)**: Tail of previous sub-section for seamless continuation
- Both injected into user messages with clear section headers

### Improved: Sub-Section Generation

- Dynamic sub-section count: 1–4 based on `target_length` (≤700 → 1, ≤1400 → 2, ≤2500 → 3, else 4)
- Per-sub-section word targets and max_tokens scaling
- TPM throttling estimates sum all sub-sections in a chapter

### Improved: Frontend

- Live markdown rendering during streaming (throttled at 600ms, immediate on completion)
- `marked.js` integration for rich content display
- Duplicate H1 detection in exports (prevents `# Title` appearing twice)
- TPM-specific wait notifications (distinguishes TPM limit from generic 429)
- Chapter count slider (3–50)
- Target length slider max increased to 4000 words

### Fixed

- Structure generation truncation for high chapter counts (solved by 3-phase approach)
- `MIN_SECTIONS=15` too aggressive — reduced to 3, allowing organic outlines
- Frontend startup freeze from `warmupApi` — added AbortController timeout + hard cap
- Invisible generated content — prose div now rendered with marked.js during streaming

### Architecture (Sentrux scan)

- Quality Signal: 0.77
- Modularity: 1.0, Acyclicity: 1.0, Depth: 1.0
- Bottleneck: file size equality (llm_service.py is large)
- Test coverage: 0% (future improvement)

---

## [0.6.0] — Previous version

- Initial Groq API integration
- Basic structure + section streaming
- Frontend with Vite + Tailwind
- PDF/TXT export
- BYOK (Bring Your Own Key) support
- Render.com deployment support
