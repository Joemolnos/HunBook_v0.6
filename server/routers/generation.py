from typing import Any, Dict, Iterator
import json
import asyncio
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

    stats_schema = GenerationStatisticsSchema(**statistics)
    return StructureResponse(statistics=stats_schema, structure=structure)


@router.post("/sections/stream")
async def stream_sections(req: SectionsStreamRequest, request: Request):
    async def event_stream():  # async generator
        cancelled = False
        # Get BYOK client once for the whole stream
        auth = request.headers.get("authorization") or request.headers.get("Authorization")
        token = None
        if auth and auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1].strip()
        try:
            client = get_groq_client(token)
        except ValueError as e:
            # Immediately emit error and end
            yield (json.dumps({"type": "error", "message": str(e)}) + "\n").encode("utf-8")
            return

        async def monitor_disconnect():
            nonlocal cancelled
            try:
                while not cancelled:
                    if await request.is_disconnected():
                        cancelled = True
                        break
                    await asyncio.sleep(0.1)
            except Exception:
                # If we can't monitor, just exit the monitor
                cancelled = True

        monitor_task = asyncio.create_task(monitor_disconnect())

        def is_cancelled() -> bool:
            return cancelled

        try:
            # Try to pass cancellation callback; fall back if monkeypatched fake doesn't accept it
            try:
                gen = llm_service.iter_sections_stream(req.structure, req.params, is_cancelled=is_cancelled, client=client)
            except TypeError:
                gen = llm_service.iter_sections_stream(req.structure, req.params)

            for event in gen:
                yield (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")
        except Exception as e:
            err = {"type": "error", "message": f"Streaming failed: {e}"}
            yield (json.dumps(err, ensure_ascii=False) + "\n").encode("utf-8")
        finally:
            cancelled = True
            try:
                monitor_task.cancel()
            except Exception:
                pass

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


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
    headers = {"Content-Disposition": f"attachment; filename={req.filename or 'generated_book'}.txt"}
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
                raise HTTPException(status_code=500, detail=f"PDF export unavailable: {e}")
        buf = func(req.content)  # type: ignore
        data = buf.getvalue()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF export failed: {e}")
    headers = {"Content-Disposition": f"attachment; filename={req.filename or 'generated_book'}.pdf"}
    return Response(content=data, media_type="application/pdf", headers=headers)
