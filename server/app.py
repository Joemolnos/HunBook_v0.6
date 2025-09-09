import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers.generation import router as generation_router
from config import REQUIRE_BYOK


def get_allowed_origins() -> list[str]:
    origins_env = os.getenv("FRONTEND_ORIGIN", "*")
    # Support comma-separated list
    if "," in origins_env:
        return [o.strip() for o in origins_env.split(",") if o.strip()]
    return [origins_env] if origins_env else ["*"]


app = FastAPI(title="Groqbook API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}

@app.get("/config")
async def get_config():
    return {"require_byok": REQUIRE_BYOK}


app.include_router(generation_router)
