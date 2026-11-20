import asyncio
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .runner import HAS_PYTHON_CHESS, execute_pair_benchmark
from .schemas import BenchmarkRequest, PairBenchmarkResponse

app = FastAPI(
    title="Vertex Model Benchmark API",
    version="0.2.0",
    docs_url="/docs",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

_run_semaphore = asyncio.Semaphore(settings.max_concurrent_runs)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Error interno al procesar la evaluación del modelo."},
    )


@app.get("/health")
async def health_check() -> dict[str, object]:
    return {
        "status": "ok",
        "mode": "paralelo" if settings.parallel_runs else "secuencial",
        "warmup": settings.warmup,
        "chess_legality": HAS_PYTHON_CHESS,
    }


@app.get("/api/v1/models")
async def list_models() -> dict[str, list[str]]:
    url = f"{settings.lm_studio_base_url.rstrip('/')}/models"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            payload = resp.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="No se pudo consultar LM Studio en el puerto configurado.",
        )

    keywords = [k.lower() for k in settings.excluded_model_keywords]
    ids = sorted(
        item["id"]
        for item in (payload.get("data") or [])
        if isinstance(item, dict)
        and isinstance(item.get("id"), str)
        and not any(k in item["id"].lower() for k in keywords)
    )
    return {"models": ids}


@app.post("/api/v1/benchmarks/pair", response_model=PairBenchmarkResponse)
async def benchmark_pair(request: BenchmarkRequest) -> PairBenchmarkResponse:
    async with _run_semaphore:
        try:
            left, right = await execute_pair_benchmark(
                model_a=request.model_a,
                model_b=request.model_b,
                suite_id=request.suite_id,
                prompt=request.prompt,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
            )
        except httpx.TimeoutException:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Tiempo de espera agotado consultando el modelo local.",
            )
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=(
                    f"LM Studio respondió {exc.response.status_code}. "
                    "Revisa que el modelo exista y que quepa en la VRAM."
                ),
            )
        except httpx.HTTPError:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Error de comunicación con el servidor de inferencia local.",
            )

    return PairBenchmarkResponse(
        run_id=str(uuid4()),
        mode="paralelo" if settings.parallel_runs else "secuencial",
        left=left,
        right=right,
    )
