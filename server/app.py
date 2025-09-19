import os
import logging
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import asyncio
import time
import json
import re

try:
    import psutil  # optional; stream returns partial data if missing
except Exception:  # pragma: no cover
    psutil = None

from .routers.generation import router as generation_router
from config import REQUIRE_BYOK, GROQ_API_KEY


def get_allowed_origins() -> list[str]:
    origins_env = os.getenv("FRONTEND_ORIGIN", "*")
    # Support comma-separated list
    if "," in origins_env:
        return [o.strip() for o in origins_env.split(",") if o.strip()]
    return [origins_env] if origins_env else ["*"]


app = FastAPI(title="Groqbook API", version="1.0.0")

# CORS configuration: prefer explicit origins; fall back to wildcard without credentials
origins = ["*"]
origin_regex = None
# On this app we do not depend on cookies; use wildcard CORS to maximize reliability across spin-ups and proxies.
allow_credentials_flag = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=origin_regex,
    allow_credentials=allow_credentials_flag,
    allow_methods=["*"],
    allow_headers=["*"],
    max_age=0,  # avoid stale preflight caching across domain/config changes
)


# ---- Lightweight runtime metrics ----
class _MetricsSampler:
    def __init__(self, interval_s: float = 1.0):
        self.interval_s = float(interval_s)
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._last: dict = {}
        self._proc = None
        self._app = None
        self._last_tick: float | None = None

    async def _run(self):
        # Initialize psutil process if available
        if psutil is not None:
            try:
                self._proc = psutil.Process()
                # prime CPU percent measurement window
                try:
                    self._proc.cpu_percent(interval=None)
                except Exception:
                    pass
            except Exception:
                self._proc = None
        while not self._stop.is_set():
            t0 = time.time()
            sample = {"ts": t0}
            try:
                if self._proc is not None and psutil is not None:
                    cpu = None
                    try:
                        cpu = self._proc.cpu_percent(interval=None)
                    except Exception:
                        cpu = None
                    try:
                        mi = self._proc.memory_info()
                        rss_mb = mi.rss / (1024 * 1024)
                        mem_pct = self._proc.memory_percent()
                        threads = self._proc.num_threads()
                        fds = None
                        try:
                            fds = self._proc.num_fds()  # linux only
                        except Exception:
                            fds = None
                        sample.update({
                            "cpu_percent": cpu,
                            "mem_rss_mb": round(rss_mb, 1),
                            "mem_percent": round(mem_pct, 1),
                            "threads": threads,
                            "fds": fds,
                        })
                    except Exception:
                        pass
                # Event loop lag (how late we are vs expected tick)
                if self._last_tick is not None:
                    expected = self._last_tick + self.interval_s
                    lag = max(0.0, t0 - expected)
                    sample["loop_lag_ms"] = int(lag * 1000)
                else:
                    sample["loop_lag_ms"] = 0
                # In-flight requests if tracked
                if self._app is not None:
                    inflight = getattr(self._app.state, "inflight", 0)
                    sample["inflight"] = int(inflight)
            finally:
                self._last = sample
                self._last_tick = t0
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self.interval_s)
                except asyncio.TimeoutError:
                    pass

    def start(self, app: FastAPI):
        if self._task is None:
            self._app = app
            self._stop.clear()
            self._task = asyncio.create_task(self._run())

    async def stop(self):
        if self._task is not None:
            self._stop.set()
            try:
                await self._task
            except Exception:
                pass
            self._task = None


@app.middleware("http")
async def _track_inflight(request: Request, call_next):
    app.state.inflight = int(getattr(app.state, "inflight", 0)) + 1
    try:
        return await call_next(request)
    finally:
        app.state.inflight = int(getattr(app.state, "inflight", 1)) - 1


@app.on_event("startup")
async def _start_metrics():
    try:
        logging.getLogger("uvicorn.error").info(
            "CORS config: origins=%s regex=%s allow_credentials=%s",
            origins,
            origin_regex,
            allow_credentials_flag,
        )
    except Exception:
        pass
    interval = float(os.getenv("METRICS_INTERVAL_S", "1.0") or 1.0)
    app.state.metrics = _MetricsSampler(interval_s=interval)
    app.state.metrics.start(app)


@app.on_event("shutdown")
async def _stop_metrics():
    m = getattr(app.state, "metrics", None)
    if m:
        await m.stop()


@app.get("/metrics")
async def get_metrics():
    """Return the latest resource snapshot as JSON."""
    m = getattr(app.state, "metrics", None)
    data = m._last if m else {}
    return data


@app.get("/metrics/stream")
async def stream_metrics(request: Request):
    """Stream NDJSON metrics at the configured interval."""
    async def gen():
        while True:
            if await request.is_disconnected():
                break
            m = getattr(app.state, "metrics", None)
            data = m._last if m else {}
            yield (json.dumps(data) + "\n").encode("utf-8")
            await asyncio.sleep(getattr(m, "interval_s", 1.0))
    return StreamingResponse(gen(), media_type="application/x-ndjson")


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/config")
async def get_config():
    return {"require_byok": REQUIRE_BYOK, "has_server_key": bool(GROQ_API_KEY)}


app.include_router(generation_router)
