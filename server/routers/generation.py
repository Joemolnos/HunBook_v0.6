from __future__ import annotations
import json
import asyncio
import os
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Header
from fastapi.responses import StreamingResponse, Response
from io import BytesIO
import logging

from ..schemas import (
    StructureRequest,
    StructureResponse,
    SectionsStreamRequest,
    ExportRequest,
)
from ..services.llm_service import generate_book_structure_service, iter_sections_stream
from ..quota import get_quota_manager, account_id_from_token
from exporting import create_markdown_file, create_pdf_file
from config import groq_client, REQUIRE_BYOK

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_client_from_header(authorization: Optional[str]):
    """Extract client from BYOK header if present."""
    if not authorization:
        if REQUIRE_BYOK:
            raise HTTPException(status_code=401, detail="BYOK required but no Authorization header provided")
        return groq_client
    
    # Strip "Bearer " prefix if present
    token = authorization
    if token.lower().startswith("bearer "):
        token = token[7:]
    
    # Create a Groq client with the user's API key
    try:
        from groq import Groq
        return Groq(api_key=token)
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid API key: {str(e)}")


@router.get("/api/key/validate")
async def validate_key(authorization: Optional[str] = Header(None)):
    """Rapid BYOK key validation endpoint."""
    if not authorization:
        raise HTTPException(status_code=401, detail="No authorization header")
    
    try:
        client = _get_client_from_header(authorization)
        # Quick test call
        response = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=[{"role": "user", "content": "test"}],
            max_tokens=1,
        )
        return {"valid": True}
    except Exception as e:
        # Only raise 401 for actual auth failures
        error_str = str(e).lower()
        if "401" in error_str or "unauthorized" in error_str or "invalid" in error_str:
            raise HTTPException(status_code=401, detail="Invalid API key")
        return {"valid": True}  # Other errors don't invalidate the key


@router.get("/api/quota")
async def get_quota(request: Request, authorization: Optional[str] = Header(None)):
    """Get current quota status."""
    quota_mgr = get_quota_manager()
    account_id = account_id_from_token(authorization, request.client.host if request.client else None)
    remaining = quota_mgr.get_remaining(account_id)
    total = quota_mgr.per_day
    used = total - remaining
    
    return {
        "used": used,
        "remaining": remaining,
        "total": total,
        "percentage": int((used / total) * 100) if total > 0 else 0,
    }


@router.post("/api/structure", response_model=StructureResponse)
async def generate_structure(
    req: StructureRequest,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    """Generate book structure/outline."""
    # Check quota
    quota_mgr = get_quota_manager()
    account_id = account_id_from_token(authorization, request.client.host if request.client else None)
    allowed, remaining = quota_mgr.consume_if_allowed(account_id)
    
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Daily quota exceeded. Please try again tomorrow.",
        )
    
    # Get client (server or BYOK)
    client = _get_client_from_header(authorization)
    
    try:
        stats_dict, structure = generate_book_structure_service(
            req.subject,
            req.params,
            client=client,
        )
        
        return StructureResponse(
            statistics=stats_dict,
            structure=structure,
        )
    except Exception as e:
        logger.error(f"Structure generation error: {e}", exc_info=True)
        error_msg = str(e).lower()
        if "429" in error_msg or "rate" in error_msg:
            raise HTTPException(status_code=429, detail=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/sections/stream")
async def stream_sections(
    req: SectionsStreamRequest,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    """Stream section generation with NDJSON."""
    client = _get_client_from_header(authorization)
    
    # Track disconnection
    disconnected = False
    
    async def is_cancelled():
        return disconnected or await request.is_disconnected()
    
    async def generate():
        nonlocal disconnected
        try:
            # Run the blocking generator in a thread pool
            loop = asyncio.get_event_loop()
            iterator = iter_sections_stream(
                req.structure,
                req.params,
                is_cancelled=lambda: disconnected,
                client=client,
                start_index=req.start_index or 0,
                count=req.count,
            )
            
            for event in iterator:
                if await is_cancelled():
                    disconnected = True
                    yield (json.dumps({"type": "aborted"}) + "\n").encode("utf-8")
                    break
                
                yield (json.dumps(event) + "\n").encode("utf-8")
                
                # Allow other tasks to run
                await asyncio.sleep(0)
                
        except Exception as e:
            logger.error(f"Stream error: {e}", exc_info=True)
            error_payload = {"type": "error", "message": str(e)}
            yield (json.dumps(error_payload) + "\n").encode("utf-8")
    
    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/api/export/markdown")
async def export_markdown(req: ExportRequest):
    """Export content as markdown/text file."""
    try:
        file_buffer = create_markdown_file(req.content)
        filename = req.filename or "generated_book"
        if not filename.endswith(".txt"):
            filename = f"{filename}.txt"
        
        return Response(
            content=file_buffer.read(),
            media_type="text/plain; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Access-Control-Expose-Headers": "Content-Disposition",
            },
        )
    except Exception as e:
        logger.error(f"Markdown export error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/export/pdf")
async def export_pdf(req: ExportRequest):
    """Export content as PDF file."""
    try:
        file_buffer = create_pdf_file(req.content)
        filename = req.filename or "generated_book"
        if not filename.endswith(".pdf"):
            filename = f"{filename}.pdf"
        
        return Response(
            content=file_buffer.read(),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Access-Control-Expose-Headers": "Content-Disposition",
            },
        )
    except Exception as e:
        logger.error(f"PDF export error: {e}", exc_info=True)
        # Try fallback to fpdf2 if weasyprint fails
        try:
            from fpdf import FPDF
            
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", size=12)
            
            # Simple text-only PDF as fallback
            for line in req.content.split('\n'):
                pdf.multi_cell(0, 10, txt=line)
            
            pdf_bytes = pdf.output(dest='S').encode('latin-1')
            filename = req.filename or "generated_book"
            if not filename.endswith(".pdf"):
                filename = f"{filename}.pdf"
            
            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={
                    "Content-Disposition": f'attachment; filename="{filename}"',
                    "Access-Control-Expose-Headers": "Content-Disposition",
                },
            )
        except Exception as fallback_error:
            logger.error(f"PDF fallback error: {fallback_error}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"PDF export failed: {str(e)}")

