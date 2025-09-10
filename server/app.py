import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import re

from .routers.generation import router as generation_router
from config import REQUIRE_BYOK


def get_allowed_origins() -> list[str]:
    origins_env = os.getenv("FRONTEND_ORIGIN", "*")
    # Support comma-separated list
    if "," in origins_env:
        return [o.strip() for o in origins_env.split(",") if o.strip()]
    return [origins_env] if origins_env else ["*"]


app = FastAPI(title="Groqbook API", version="1.0.0")

# CORS configuration: prefer explicit origins; optionally allow regex fallback
origins = get_allowed_origins()
origin_regex = os.getenv("FRONTEND_ORIGIN_REGEX", None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    max_age=86400,
)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}

@app.get("/config")
async def get_config():
    return {"require_byok": REQUIRE_BYOK}


app.include_router(generation_router)
