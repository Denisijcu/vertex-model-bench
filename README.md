# Vertex Model Benchmark Arena

Dashboard para comparar lado a lado modelos locales servidos por **LM Studio** (endpoint compatible con OpenAI en `http://localhost:1234/v1`) en dos suites: **Tool-Calling (dry-run)** y **Ajedrez (SAN)**. Mide TTFT, latencia total, velocidad de decodificación y tokens generados, y valida la estructura de la respuesta.

Desarrollado por **Vertex Coders LLC**.

## Arquitectura

| Parte | Carpeta | Stack | Puerto |
|---|---|---|---|
| Backend | `vertex-model-bench-api` | FastAPI + Pydantic v2 + `httpx` asíncrono | `127.0.0.1:8015` |
| Frontend | `vertex-model-bench-ui` | Angular 21 (standalone, Signals, OnPush) + Angular Material 3 oscuro | `127.0.0.1:4200` |

```text
vertex-model-bench/
├── start-bench.ps1
├── Guia de operacion.md
├── vertex-model-bench-api/
│   ├── app/
│   │   ├── config.py      # ajustes (.env): modo secuencial/paralelo, warmup, timeouts
│   │   ├── main.py        # endpoints
│   │   ├── runner.py      # streaming contra LM Studio + validadores
│   │   └── schemas.py
│   └── requirements.txt
└── vertex-model-bench-ui/
    └── src/app/
        ├── core/models/benchmark.models.ts
        ├── core/services/benchmark-api.service.ts
        └── features/arena/
            ├── arena-dashboard.component.*        # controles y layout
            └── model-result-card/                  # tarjeta de resultados (A y B)
```

## Cómo mide

- **Secuencial por defecto.** Modelo A y luego modelo B, cada uno con la GPU solo para él. En paralelo los dos compiten por la misma GPU y los tok/s salen contaminados (se puede activar con `PARALLEL_RUNS=true`, sabiendo eso).
- **Warmup.** Antes de medir cada modelo se le manda una petición de 1 token, para que el TTFT no incluya el tiempo que LM Studio tarda en cargarlo (JIT).
- **Tokens reales.** Se pide `stream_options.include_usage`. Si el runtime no manda `usage`, se cuentan los eventos del stream y la tarjeta lo marca como *estimado*.
- **tok/s** = tokens de decodificación entre el primer y el último token (no incluye el TTFT).
- **Tool-Calling:** extrae el JSON (acepta bloques ```` ``` ```` y quita `<think>`), comprueba la allowlist (`query_telemetry`, `inspect_position`), las claves requeridas y sus tipos. Nunca ejecuta nada.
- **Ajedrez:** busca jugadas SAN fuera del propio FEN. Con `python-chess` instalado exige además que la jugada sea **legal** en la posición; sin él, solo comprueba el formato.

## Puesta en marcha

Backend, desde `E:\vertex-model-bench\vertex-model-bench-api`:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Frontend, desde `E:\vertex-model-bench\vertex-model-bench-ui`:

```powershell
npm install
```

Arranque de las dos partes, desde `E:\vertex-model-bench`:

```powershell
.\start-bench.ps1
```

## Endpoints

- `GET /health` — estado, modo (`secuencial`/`paralelo`), warmup y si hay validación de legalidad.
- `GET /api/v1/models` — modelos de chat de LM Studio (filtra embeddings y modelos de imagen).
- `POST /api/v1/benchmarks/pair` — corre `model_a` y `model_b` en la suite `tool-calling` o `chess`.

Ejemplo de payload:

```json
{
  "model_a": "vertex-nemotron-core-4b",
  "model_b": "vertex-gemma-2b-mcp",
  "suite_id": "chess",
  "temperature": 0.2,
  "max_tokens": 512
}
```

## Variables de entorno (`vertex-model-bench-api/.env`, opcional)

| Variable | Por defecto | Qué hace |
|---|---|---|
| `LM_STUDIO_BASE_URL` | `http://localhost:1234/v1` | Endpoint OpenAI-compatible |
| `LM_STUDIO_TIMEOUT_SEC` | `120` | Timeout de cada corrida |
| `WARMUP_TIMEOUT_SEC` | `180` | Timeout de la carga del modelo |
| `WARMUP` | `true` | Precalentar antes de medir |
| `PARALLEL_RUNS` | `false` | Correr A y B a la vez |
| `MAX_CONCURRENT_RUNS` | `1` | Comparaciones simultáneas |

## Seguridad

- Los tool calls se inspeccionan en dry-run contra una allowlist y nunca se ejecutan en el host.
- CORS restringido a `localhost:4200` y `127.0.0.1:4200`; la API solo escucha en `127.0.0.1`.
- Los errores no controlados devuelven un mensaje genérico, sin trazas internas.
