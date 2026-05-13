"""
mcp_service.py — Multi-call MCP pipeline with server-type detection,
query decomposition, tool chaining, and parallel multi-query execution.

Pipeline per config:
  1. Fetch + cache tool list
  2. Classify server type (context7 / wikipedia / web_search / generic)
  3. Decompose query into 2-3 targeted sub-queries
  4. Build and execute call plan (sequential chains or parallel batches)
  5. Merge + deduplicate results
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import re
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.client.sse import sse_client

if TYPE_CHECKING:
    from ..schemas import MCPConfig

logger = logging.getLogger(__name__)

_MCP_TIMEOUT = 20        # seconds: total budget per MCP multi-call sequence
_MCP_INNER_TIMEOUT = 10  # seconds: asyncio-level timeout inside each network op

# ── Tool list cache ───────────────────────────────────────────────────────────
_tool_cache: dict[str, tuple[list, float]] = {}
_TOOL_CACHE_TTL = 300  # seconds — refresh after 5 min


def _run_async(coro, timeout: int = _MCP_TIMEOUT):
    """Run an async coroutine in a dedicated thread — never conflicts with
    the FastAPI event loop running in the main thread."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, asyncio.wait_for(coro, timeout=timeout - 1))
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            logger.warning("MCP call timed out after %ds (thread-level)", timeout)
            raise TimeoutError(f"MCP call timed out after {timeout}s")


# ── Server classification ─────────────────────────────────────────────────────

def _classify_server(url: str, tools: List[Dict[str, Any]]) -> str:
    """Detect server type from URL and tool names.
    Returns one of: 'context7', 'wikipedia', 'web_search', 'generic'.
    """
    u = url.lower()
    names = {t["name"].lower() for t in tools}

    if "context7" in u or "resolve-library-id" in names:
        return "context7"

    if (
        "wikipedia" in u
        or ("search" in names and any("page" in n for n in names))
        or any("wikipedia" in n for n in names)
    ):
        return "wikipedia"

    if any(kw in u for kw in ("brave", "tavily", "serper", "googlesearch", "websearch", "bing", "duckduck")):
        return "web_search"

    # Tool-name heuristic for web search when URL is neutral
    if any(kw in n for n in names for kw in ("web_search", "internet_search", "brave_search", "tavily_search")):
        return "web_search"

    return "generic"


# ── Query decomposition ───────────────────────────────────────────────────────

def _decompose_query(query: str, phase: str) -> List[str]:
    """Generate 2-3 targeted sub-queries from a single query string.

    pre_structure: book-level topic → overview, concepts, trends
    per_section:   chapter title+desc → direct, examples, background
    """
    q = query.strip()
    # Extract a short title from "Title: description" format
    title = q.split(":")[0].strip() if ":" in q else q

    if phase == "pre_structure":
        return [
            q,
            f"{title} key concepts terminology fundamentals",
            f"{title} recent developments trends 2024 2025",
        ]
    else:
        # per_section
        return [
            q,
            f"{title} concrete examples real-world applications case studies",
            f"{title} mechanisms theory history background",
        ]


# ── Tool selection (single best) ──────────────────────────────────────────────

def _score_tool(tool: Dict[str, Any], query: str) -> float:
    tokens = set(re.findall(r"[a-záéíóöőúüűA-ZÁÉÍÓÖŐÚÜŰ]+", query.lower()))
    if not tokens:
        return 0.0
    name_tokens = set(re.findall(r"[a-z]+", (tool.get("name") or "").lower()))
    desc_tokens = set(re.findall(r"[a-z]+", (tool.get("description") or "").lower()))
    score = (len(tokens & name_tokens) * 2 + len(tokens & desc_tokens)) / len(tokens)
    name = (tool.get("name") or "").lower()
    desc = (tool.get("description") or "").lower()
    if any(kw in name or kw in desc for kw in ("search", "query", "find", "lookup", "retrieve")):
        score += 0.5
    return score


def select_best_tool(tools: List[Dict[str, Any]], query: str) -> Dict[str, Any]:
    if not tools:
        raise ValueError("No tools available on this MCP server.")
    if len(tools) == 1:
        return tools[0]
    scored = sorted(tools, key=lambda t: _score_tool(t, query), reverse=True)
    return scored[0]


def _find_tool_by_name(tools: List[Dict[str, Any]], name: str) -> Optional[Dict[str, Any]]:
    """Find a tool by exact name (case-insensitive)."""
    for t in tools:
        if (t.get("name") or "").lower() == name.lower():
            return t
    return None


# ── Tool argument builder ─────────────────────────────────────────────────────

def _build_tool_args(tool: Dict[str, Any], query: str, max_results: int) -> dict:
    """Build call arguments by inspecting the tool's inputSchema."""
    name = (tool.get("name") or "").lower()
    schema = tool.get("inputSchema") or {}
    props: dict = schema.get("properties") or {}

    args: dict = {}

    query_keys = [k for k in props if any(kw in k.lower() for kw in ("query", "q", "search", "text", "input", "prompt"))]
    topic_keys = [k for k in props if any(kw in k.lower() for kw in ("topic", "subject", "keyword"))]
    lib_keys   = [k for k in props if any(kw in k.lower() for kw in ("library", "package", "lib", "module"))]
    limit_keys = [k for k in props if any(kw in k.lower() for kw in ("limit", "max", "count", "num", "results", "top_k"))]
    token_keys = [k for k in props if any(kw in k.lower() for kw in ("tokens", "max_tokens"))]

    if query_keys:
        args[query_keys[0]] = query
    elif lib_keys:
        args[lib_keys[0]] = query
    else:
        required = schema.get("required") or []
        for rk in required:
            if rk not in args:
                args[rk] = query
                break
        if not args:
            args["query"] = query

    if topic_keys and topic_keys[0] not in args:
        args[topic_keys[0]] = query
    if limit_keys:
        args[limit_keys[0]] = max_results
    if token_keys:
        args[token_keys[0]] = 4000

    # Named pattern overrides (well-known servers)
    if "resolve" in name or "library-id" in name:
        args = {"libraryName": query}
    elif "query-docs" in name or "get-library-docs" in name:
        # Called with resolved library ID if available, else with topic
        args = {"context7CompatibleLibraryID": query, "topic": query, "tokens": 4000}

    return args


# ── Result helpers ────────────────────────────────────────────────────────────

def _extract_text(result, max_results: int) -> str:
    texts: list[str] = []
    for item in result.content:
        text = getattr(item, "text", None)
        if text:
            texts.append(text.strip())
        if len(texts) >= max_results:
            break
    return "\n\n---\n\n".join(texts)


def _extract_first_line(text: str) -> str:
    """Return first non-empty line — useful for extracting a library ID."""
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line
    return text[:200].strip()


# ── Result merge & dedup ──────────────────────────────────────────────────────

def _jaccard(a: str, b: str, n: int = 4) -> float:
    """Compute n-gram Jaccard similarity between two strings."""
    def ngrams(s: str) -> set[str]:
        s = s.lower()
        return {s[i: i + n] for i in range(max(0, len(s) - n + 1))}

    sa, sb = ngrams(a), ngrams(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _merge_results(
    results: List[Tuple[str, str, str]],  # (tool_name, query_angle, text)
    max_chars: int = 8000,
) -> str:
    """Merge multiple results, deduplicate similar ones, add headers, truncate."""
    kept: List[Tuple[str, str, str]] = []

    for tool_name, query_angle, text in results:
        if not text or not text.strip():
            continue
        # Deduplicate: skip if very similar to an already-kept result
        too_similar = any(
            _jaccard(text[:500], prev_text[:500]) > 0.65
            for _, _, prev_text in kept
        )
        if too_similar:
            logger.debug("MCP merge: skipping near-duplicate result for '%s'", query_angle[:60])
            continue
        kept.append((tool_name, query_angle, text))

    if not kept:
        return ""

    parts: list[str] = []
    total = 0
    for tool_name, query_angle, text in kept:
        header = f"[{tool_name} | {query_angle[:80]}]"
        # Truncate individual result if needed
        remaining = max_chars - total - len(header) - 20
        if remaining <= 100:
            break
        snippet = text[:remaining]
        block = f"{header}\n{snippet}"
        parts.append(block)
        total += len(block) + 4  # +4 for separator

    return "\n\n---\n\n".join(parts)


# ── Async session helpers ─────────────────────────────────────────────────────

async def _do_in_session(url: str, headers: dict, fn):
    """Try streamablehttp then SSE; call fn(session) and return result."""
    async def _run_fn(read, write):
        async with ClientSession(read, write) as session:
            await asyncio.wait_for(session.initialize(), timeout=_MCP_INNER_TIMEOUT)
            return await fn(session)

    try:
        async with streamablehttp_client(url, headers=headers) as (read, write, _):
            return await _run_fn(read, write)
    except Exception as exc:
        logger.warning("streamablehttp failed (%s), trying SSE", exc)

    try:
        async with sse_client(url, headers=headers) as (read, write):
            return await _run_fn(read, write)
    except Exception as exc2:
        msg = str(exc2)
        if "401" in msg or "403" in msg or "Unauthorized" in msg:
            raise RuntimeError(f"MCP auth failed for {url} — check the auth token") from exc2
        raise RuntimeError(f"MCP call failed on both transports: {exc2}") from exc2


async def _list_tools_with_details_async(url: str, token: Optional[str]) -> List[Dict[str, Any]]:
    """Return list of {name, description, inputSchema} dicts. Cached for TTL."""
    cache_key = f"{url}|{token or ''}"
    cached = _tool_cache.get(cache_key)
    if cached and (time.monotonic() - cached[1]) < _TOOL_CACHE_TTL:
        return cached[0]

    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    async def _fn(session: ClientSession):
        result = await asyncio.wait_for(session.list_tools(), timeout=_MCP_INNER_TIMEOUT)
        return [
            {
                "name": t.name,
                "description": t.description or "",
                "inputSchema": (
                    t.inputSchema.model_dump()
                    if hasattr(t.inputSchema, "model_dump")
                    else (t.inputSchema or {})
                ),
            }
            for t in result.tools
        ]

    tools = await _do_in_session(url, headers, _fn)
    _tool_cache[cache_key] = (tools, time.monotonic())
    return tools


async def _call_tool_raw_async(
    url: str,
    token: Optional[str],
    tool: Dict[str, Any],
    query: str,
    max_results: int,
    extra_args: Optional[dict] = None,
) -> str:
    """Call a single tool and return extracted text."""
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    tool_args = _build_tool_args(tool, query, max_results)
    if extra_args:
        tool_args.update(extra_args)

    tool_name = tool["name"]
    logger.info("MCP calling tool '%s' args=%s", tool_name, list(tool_args.keys()))

    async def _fn(session: ClientSession):
        result = await asyncio.wait_for(
            session.call_tool(tool_name, tool_args),
            timeout=_MCP_INNER_TIMEOUT,
        )
        return _extract_text(result, max_results)

    return await _do_in_session(url, headers, _fn)


# ── Server-type specific execution strategies ─────────────────────────────────

async def _execute_context7(
    cfg: "MCPConfig",
    tools: List[Dict[str, Any]],
    sub_queries: List[str],
) -> List[Tuple[str, str, str]]:
    """Context7: resolve-library-id → get-library-docs (sequential chain)."""
    results: List[Tuple[str, str, str]] = []
    q_main = sub_queries[0]

    resolve_tool = _find_tool_by_name(tools, "resolve-library-id")
    docs_tool = _find_tool_by_name(tools, "get-library-docs")

    # Fallback: if tools not found by exact name, use best match
    if not resolve_tool:
        resolve_tool = next(
            (t for t in tools if "resolve" in t["name"].lower() or "library-id" in t["name"].lower()),
            None,
        )
    if not docs_tool:
        docs_tool = next(
            (t for t in tools if "docs" in t["name"].lower() or "get-library" in t["name"].lower()),
            None,
        )

    # If we have both tools, run the sequential chain
    if resolve_tool and docs_tool:
        try:
            logger.info("Context7: resolving library for '%s'", q_main[:60])
            resolved_text = await _call_tool_raw_async(
                cfg.server_url, cfg.auth_token, resolve_tool, q_main, 1,
            )
            # Extract library ID from first line of result
            library_id = _extract_first_line(resolved_text) if resolved_text else ""
            if library_id and not library_id.startswith("[") and len(library_id) < 200:
                logger.info("Context7: resolved library_id='%s', fetching docs", library_id)
                docs_text = await _call_tool_raw_async(
                    cfg.server_url, cfg.auth_token, docs_tool, library_id,
                    cfg.max_results,
                    extra_args={"context7CompatibleLibraryID": library_id, "topic": q_main, "tokens": 4000},
                )
                if docs_text:
                    results.append((docs_tool["name"], q_main, docs_text))
            else:
                # Resolution returned nothing useful — fall through to direct call
                logger.info("Context7: resolution empty, falling back to direct docs call")
                docs_text = await _call_tool_raw_async(
                    cfg.server_url, cfg.auth_token, docs_tool, q_main,
                    cfg.max_results,
                    extra_args={"context7CompatibleLibraryID": q_main, "topic": q_main, "tokens": 4000},
                )
                if docs_text:
                    results.append((docs_tool["name"], q_main, docs_text))
        except Exception as exc:
            logger.warning("Context7 chain failed: %s", exc)

    elif docs_tool:
        # Only docs tool available
        try:
            text = await _call_tool_raw_async(
                cfg.server_url, cfg.auth_token, docs_tool, q_main, cfg.max_results,
                extra_args={"context7CompatibleLibraryID": q_main, "topic": q_main, "tokens": 4000},
            )
            if text:
                results.append((docs_tool["name"], q_main, text))
        except Exception as exc:
            logger.warning("Context7 docs-only call failed: %s", exc)

    else:
        # No recognized tools — fall back to generic
        logger.info("Context7 tools not found by name, falling back to generic strategy")
        results = await _execute_generic(cfg, tools, sub_queries)

    return results


async def _execute_wikipedia(
    cfg: "MCPConfig",
    tools: List[Dict[str, Any]],
    sub_queries: List[str],
) -> List[Tuple[str, str, str]]:
    """Wikipedia: search(q1+q2) in parallel → get_page(top hit from q1)."""
    results: List[Tuple[str, str, str]] = []

    search_tool = _find_tool_by_name(tools, "search") or select_best_tool(tools, "search")
    page_tool = next(
        (t for t in tools if any(kw in t["name"].lower() for kw in ("get_page", "get-page", "page", "read"))),
        None,
    )

    q1, q2 = sub_queries[0], sub_queries[1] if len(sub_queries) > 1 else sub_queries[0]

    # Step 1: parallel search
    search_tasks = [
        _call_tool_raw_async(cfg.server_url, cfg.auth_token, search_tool, q, cfg.max_results)
        for q in [q1, q2]
    ]
    search_results = await asyncio.gather(*search_tasks, return_exceptions=True)

    top_title: Optional[str] = None
    for q, sr in zip([q1, q2], search_results):
        if isinstance(sr, Exception):
            logger.warning("Wikipedia search failed for '%s': %s", q[:60], sr)
            continue
        if sr:
            results.append((search_tool["name"], q, sr))
            if top_title is None:
                # Try to extract first article title from search result
                for line in sr.splitlines():
                    if line.strip():
                        top_title = line.strip()[:100]
                        break

    # Step 2: get full page for top result
    if page_tool and top_title:
        try:
            logger.info("Wikipedia: fetching page '%s'", top_title)
            page_text = await _call_tool_raw_async(
                cfg.server_url, cfg.auth_token, page_tool, top_title, cfg.max_results,
            )
            if page_text:
                results.append((page_tool["name"], f"full page: {top_title}", page_text))
        except Exception as exc:
            logger.warning("Wikipedia get_page failed for '%s': %s", top_title, exc)

    return results


async def _execute_web_search(
    cfg: "MCPConfig",
    tools: List[Dict[str, Any]],
    sub_queries: List[str],
) -> List[Tuple[str, str, str]]:
    """Web search: run all sub-queries in parallel."""
    results: List[Tuple[str, str, str]] = []
    best_tool = select_best_tool(tools, sub_queries[0])

    tasks = [
        _call_tool_raw_async(cfg.server_url, cfg.auth_token, best_tool, q, cfg.max_results)
        for q in sub_queries
    ]
    responses = await asyncio.gather(*tasks, return_exceptions=True)

    for q, resp in zip(sub_queries, responses):
        if isinstance(resp, Exception):
            logger.warning("Web search failed for '%s': %s", q[:60], resp)
            continue
        if resp:
            results.append((best_tool["name"], q, resp))

    return results


async def _execute_generic(
    cfg: "MCPConfig",
    tools: List[Dict[str, Any]],
    sub_queries: List[str],
) -> List[Tuple[str, str, str]]:
    """Generic: call best matching tool with top 2 query angles in parallel."""
    results: List[Tuple[str, str, str]] = []

    queries_to_run = sub_queries[:2]  # max 2 for generic to avoid overloading unknown servers
    best_tool = select_best_tool(tools, queries_to_run[0])

    tasks = [
        _call_tool_raw_async(cfg.server_url, cfg.auth_token, best_tool, q, cfg.max_results)
        for q in queries_to_run
    ]
    responses = await asyncio.gather(*tasks, return_exceptions=True)

    for q, resp in zip(queries_to_run, responses):
        if isinstance(resp, Exception):
            logger.warning("Generic MCP call failed for '%s': %s", q[:60], resp)
            continue
        if resp:
            results.append((best_tool["name"], q, resp))

    return results


# ── Multi-call per config ─────────────────────────────────────────────────────

async def _call_config_multi_async(
    cfg: "MCPConfig",
    query: str,
    phase: str,
) -> str:
    """Run the full multi-step pipeline for a single MCPConfig.

    1. Fetch tool list (cached)
    2. Classify server type
    3. Decompose query into sub-queries
    4. Execute strategy (sequential chain or parallel batch)
    5. Merge and deduplicate results
    """
    tools = await _list_tools_with_details_async(cfg.server_url, cfg.auth_token)
    if not tools:
        logger.warning("MCP server %s returned no tools", cfg.server_url)
        return ""

    server_type = _classify_server(cfg.server_url, tools)
    sub_queries = _decompose_query(query, phase)

    logger.info(
        "MCP config %s: type=%s, %d sub-queries, %d tools",
        cfg.server_url, server_type, len(sub_queries), len(tools),
    )

    if server_type == "context7":
        raw = await _execute_context7(cfg, tools, sub_queries)
    elif server_type == "wikipedia":
        raw = await _execute_wikipedia(cfg, tools, sub_queries)
    elif server_type == "web_search":
        raw = await _execute_web_search(cfg, tools, sub_queries)
    else:
        raw = await _execute_generic(cfg, tools, sub_queries)

    merged = _merge_results(raw, max_chars=8000)
    if merged:
        logger.info(
            "MCP %s: merged %d result(s) → %d chars",
            cfg.server_url, len(raw), len(merged),
        )
    return merged


# ── Parallel across all configs ───────────────────────────────────────────────

async def _call_multiple_async(
    configs: "List[MCPConfig]",
    query: str,
    phase: str,
) -> str:
    """Call all enabled configs for the given phase in parallel."""
    active = [
        c for c in configs
        if c.enabled and c.server_url
        and (
            (phase == "pre_structure" and c.pre_structure)
            or (phase == "per_section" and c.per_section)
        )
    ]
    if not active:
        return ""

    async def _one(cfg: "MCPConfig") -> str:
        try:
            return await asyncio.wait_for(
                _call_config_multi_async(cfg, query, phase),
                timeout=_MCP_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning("MCP pipeline timed out for %s (skipping)", cfg.server_url)
            return ""
        except Exception as exc:
            logger.warning("MCP pipeline failed for %s: %s", cfg.server_url, exc)
            return ""

    results = await asyncio.gather(*[_one(c) for c in active])
    parts = [r for r in results if r]
    return "\n\n═══════════════════════════════════════\n\n".join(parts)


# ── Public sync API ───────────────────────────────────────────────────────────

def list_mcp_tools(url: str, token: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return tool descriptors (name, description) from the remote MCP server."""
    return _run_async(_list_tools_with_details_async(url, token))


def call_mcp_tools_multiple(
    configs: "List[MCPConfig]",
    query: str,
    phase: str,
) -> str:
    """Call all enabled MCP configs for the given phase in parallel.
    Uses multi-step pipeline per server: classify → decompose → chain/parallel → merge.
    phase: 'pre_structure' | 'per_section'
    """
    return _run_async(_call_multiple_async(configs, query, phase), timeout=_MCP_TIMEOUT)
