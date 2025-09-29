from typing import Any, Dict, Iterator
import json
import asyncio
import threading
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse, Response

from ..schemas import (
    StructureRequest,
    StructureResponse,
    SectionsStreamRequest,
    ExportRequest,
    GenerationStatisticsSchema,
)
from ..services import llm_service
from config import get_groq_client
from ..quota import get_quota_manager, account_id_from_token

# Lazy export helpers to avoid heavy deps during import (WeasyPrint)
create_markdown_file = None  # will try import on demand
create_pdf_file = None  # will be monkeypatched in tests or imported lazily

try:
    # markdown helper doesn't need WeasyPrint, but exporting imports it; handle failures
    from exporting import create_markdown_file as _cmf  # type: ignore
    create_markdown_file = _cmf
except Exception:
    create_markdown_file = None

router = APIRouter(prefix="/api", tags=["generation"])


def _count_leaves(sections: Dict[str, Any]) -> int:
    def walk(d: Dict[str, Any]) -> int:
        n = 0
        for v in (d or {}).values():
            if isinstance(v, str):
                n += 1
            elif isinstance(v, dict):
                n += walk(v)
        return n
    try:
        return walk(sections or {})
    except Exception:
        return 0


@router.get("/key/validate")
def validate_key(request: Request):
    """Validate provided API key (or server key if BYOK is not required) by performing a lightweight call.
    Returns {ok: true} on success. Raises 401 if the key is invalid or missing.
    """
    # Extract Bearer token if present
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    token = None
    if auth and auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()
    try:
        client = get_groq_client(token)
        # Try a non-token-consuming lightweight call if available
        try:
            # Many OpenAI-compatible clients expose models.list()
            _ = client.models.list()  # type: ignore[attr-defined]
        except Exception:
            # As a fallback, perform a tiny metadata-only chat call with strict timeout; if it fails
            # due to invalid key we still surface 401.
            try:
                c = client.with_options(timeout=10)
            except Exception:
                c = client
            _ = c.chat.completions.create(
                model="openai/gpt-oss-20b",
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
                temperature=0,
                stream=False,
            )
    except Exception as e:
        msg = str(e)
        low = msg.lower()
        code = 401 if ("401" in msg or "invalid api key" in low or "api key" in low) else 500
        raise HTTPException(status_code=code, detail=f"Key validation failed: {e}")
    return {"ok": True}


@router.post("/structure", response_model=StructureResponse)
def generate_structure(req: StructureRequest, request: Request) -> StructureResponse:
    try:
        # Extract BYOK API key, if provided
        auth = request.headers.get("authorization") or request.headers.get("Authorization")
        token = None
        if auth and auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1].strip()
        client = get_groq_client(token)

        # Quota enforcement: consume 1 attempt at the start of generation
        # If client already pre-consumed, skip here to avoid double count
        preconsumed = request.headers.get("x-preconsumed")
        if not preconsumed:
            quota = get_quota_manager()
            account_id = account_id_from_token(token, getattr(request.client, "host", None))
            allowed, remaining = quota.consume_if_allowed(account_id)
            if not allowed:
                raise HTTPException(status_code=429, detail="Daily quota exceeded. Please try again tomorrow.")
        try:
            statistics, structure = llm_service.generate_book_structure_service(
                subject=req.subject,
                params=req.params,
                client=client,
            )
        except TypeError:
            # Backward-compatible with fakes not accepting client param
            statistics, structure = llm_service.generate_book_structure_service(
                subject=req.subject,
                params=req.params,
            )
    except ValueError as e:
        # Missing/invalid API key in BYOK mode
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        msg = str(e)
        low = msg.lower()
        if "401" in msg or "invalid api key" in low:
            code = 401
        elif "429" in msg or "rate limit" in low:
            code = 429
        else:
            code = 500
        raise HTTPException(status_code=code, detail=f"Structure generation failed: {e}")

    # Guard: if the refined/limited structure has no leaves, return a clear error
    if _count_leaves(structure) <= 0:
        raise HTTPException(status_code=422, detail="Empty structure generated. Please adjust the subject or try again.")

    stats_schema = GenerationStatisticsSchema(**statistics)
    return StructureResponse(statistics=stats_schema, structure=structure)


@router.post("/sections/stream")
async def stream_sections(req: SectionsStreamRequest, request: Request):
    async def event_stream():  # async generator with thread offload
        cancelled = False
        cancel_event = threading.Event()
        queue: asyncio.Queue[Dict[str, Any] | None] = asyncio.Queue(maxsize=100)

        # Get BYOK client once for the whole stream
        auth = request.headers.get("authorization") or request.headers.get("Authorization")
        token = None
        if auth and auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1].strip()
        try:
            client = get_groq_client(token)
        except ValueError as e:
            # Immediately emit error and end
            await queue.put({"type": "error", "message": str(e)})
            await queue.put(None)
            cancelled = True
            cancel_event.set()
        
        async def monitor_disconnect():
            nonlocal cancelled
            try:
                while not cancelled:
                    if await request.is_disconnected():
                        cancelled = True
                        cancel_event.set()
                        break
                    await asyncio.sleep(0.1)
            except Exception:
                cancelled = True
                cancel_event.set()

        def producer():
            if cancel_event.is_set():
                return
            try:
                # Pull events from blocking generator in a background thread
                try:
                    gen = llm_service.iter_sections_stream(
                        req.structure,
                        req.params,
                        is_cancelled=lambda: cancel_event.is_set(),
                        client=client,
                        start_index=int(getattr(req, 'start_index', 0) or 0),
                        count=getattr(req, 'count', None),
                    )
                except TypeError:
                    gen = llm_service.iter_sections_stream(req.structure, req.params)
                for ev in gen:
                    if cancel_event.is_set():
                        break
                    # Block if queue is full; this is fine in a background thread
                    asyncio.run_coroutine_threadsafe(queue.put(ev), loop)
            except Exception as e:  # pragma: no cover
                asyncio.run_coroutine_threadsafe(queue.put({"type": "error", "message": f"Streaming failed: {e}"}), loop)
            finally:
                asyncio.run_coroutine_threadsafe(queue.put(None), loop)

        # Start monitor and producer
        loop = asyncio.get_running_loop()
        monitor_task = asyncio.create_task(monitor_disconnect())
        prod_thread = threading.Thread(target=producer, name="sections-producer", daemon=True)
        prod_thread.start()

        last_sent = asyncio.get_event_loop().time()
        HEARTBEAT_S = 15.0

        try:
            while True:
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_S)
                except asyncio.TimeoutError:
                    # Heartbeat to keep proxies from idling out
                    yield (json.dumps({"type": "ping"}) + "\n").encode("utf-8")
                    last_sent = asyncio.get_event_loop().time()
                    continue

                if ev is None:
                    break
                yield (json.dumps(ev, ensure_ascii=False) + "\n").encode("utf-8")
                last_sent = asyncio.get_event_loop().time()
        finally:
            cancelled = True
            cancel_event.set()
            try:
                monitor_task.cancel()
            except Exception:
                pass
            # Do not join thread indefinitely; it's daemonized and will exit shortly

    headers = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
        # Hint for some reverse proxies (may be ignored on Render)
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(event_stream(), media_type="application/x-ndjson", headers=headers)


@router.get("/quota")
def get_quota(request: Request):
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    token = None
    if auth and auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()
    quota = get_quota_manager()
    account_id = account_id_from_token(token, getattr(request.client, "host", None))
    remaining = quota.get_remaining(account_id)
    return {"per_day": quota.per_day, "remaining": remaining}


@router.post("/quota/consume")
def consume_quota(request: Request):
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    token = None
    if auth and auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()
    quota = get_quota_manager()
    account_id = account_id_from_token(token, getattr(request.client, "host", None))
    allowed, remaining = quota.consume_if_allowed(account_id)
    if not allowed:
        raise HTTPException(status_code=429, detail="Daily quota exceeded. Please try again tomorrow.")
    return {"per_day": quota.per_day, "remaining": remaining}


@router.post("/export/markdown")
def export_markdown(req: ExportRequest):
    try:
        buf = None
        if create_markdown_file is None:
            try:
                from exporting import create_markdown_file as _cmf  # type: ignore
                buf = _cmf(req.content)
            except Exception:
                from io import BytesIO
                buf = BytesIO(req.content.encode("utf-8"))
        else:
            buf = create_markdown_file(req.content)  # type: ignore
        data = buf.getvalue()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Markdown export failed: {e}")
    headers = {
        "Content-Disposition": f"attachment; filename={req.filename or 'generated_book'}.txt",
        # Ensure CORS on Render even if middleware is bypassed
        "Access-Control-Allow-Origin": "*",
        # Expose Content-Disposition to client JS when reading headers
        "Access-Control-Expose-Headers": "Content-Disposition",
        "Cache-Control": "no-cache, no-store, must-revalidate",
    }
    return Response(content=data, media_type="text/plain; charset=utf-8", headers=headers)


@router.post("/export/pdf")
def export_pdf(req: ExportRequest):
    try:
        func = create_pdf_file
        if func is None:
            try:
                from exporting import create_pdf_file as _cpf  # type: ignore
                func = _cpf
            except Exception as e:
                func = None  # fall back to fpdf2 below
        data = None
        if func is not None:
            try:
                buf = func(req.content)  # type: ignore
                data = buf.getvalue()
            except Exception as e:
                data = None
        if data is None:
            # Fallback: generate a very simple PDF with fpdf2 so downloads always work
            try:
                from fpdf import FPDF  # type: ignore
                pdf = FPDF()
                pdf.set_auto_page_break(auto=True, margin=15)
                pdf.add_page()
                try:
                    pdf.set_font("Helvetica", size=12)
                except Exception:
                    pdf.set_font("Arial", size=12)
                # Very naive Markdown-to-text: strip headings and write lines
                for raw_line in (req.content or "").splitlines():
                    line = raw_line.strip()
                    if not line:
                        pdf.ln(5)
                        continue
                    if line.startswith("#"):
                        # Treat markdown heading as bold, slightly bigger
                        level = len(line) - len(line.lstrip('#'))
                        text = line[level:].strip()
                        try:
                            pdf.set_font("Helvetica", "B", size=max(12, 18 - level*2))
                        except Exception:
                            pdf.set_font("Arial", "B", size=max(12, 18 - level*2))
                        pdf.multi_cell(0, 8, txt=text)
                        try:
                            pdf.set_font("Helvetica", size=12)
                        except Exception:
                            pdf.set_font("Arial", size=12)
                    else:
                        pdf.multi_cell(0, 6, txt=line)
                data = pdf.output(dest='S').encode('latin1')
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"PDF export failed: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF export failed: {e}")
    headers = {
        "Content-Disposition": f"attachment; filename={req.filename or 'generated_book'}.pdf",
        # Ensure CORS on Render even if middleware is bypassed
        "Access-Control-Allow-Origin": "*",
        # Expose Content-Disposition to client JS when reading headers
        "Access-Control-Expose-Headers": "Content-Disposition",
        "Cache-Control": "no-cache, no-store, must-revalidate",
    }
    return Response(content=data, media_type="application/pdf", headers=headers)


# Explicit preflight handlers to be extra-safe on Render proxies
@router.options("/export/markdown")
def options_export_markdown():
    return Response(status_code=204, headers={
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "*",
        "Access-Control-Max-Age": "600",
    })


@router.options("/export/pdf")
def options_export_pdf():
    return Response(status_code=204, headers={
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "*",
        "Access-Control-Max-Age": "600",
    })
