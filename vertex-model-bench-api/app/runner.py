import asyncio
import json
import re
import time
from typing import Any

import httpx

from .config import settings
from .schemas import ModelRunResult, SuiteType, ToolCallValidation

try:  # python-chess es opcional: si no está, se cae al chequeo por regex
    import chess  # type: ignore

    HAS_PYTHON_CHESS = True
except ImportError:  # pragma: no cover
    chess = None  # type: ignore
    HAS_PYTHON_CHESS = False

DEFAULT_CHESS_FEN = "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4"

DEFAULT_PROMPTS: dict[SuiteType, str] = {
    SuiteType.TOOL_CALLING: (
        'Responde ÚNICAMENTE con un JSON válido con este esquema para consultar en dry-run: '
        '{"tool": "query_telemetry", "arguments": {"service": "vic-core", "window_minutes": 15}}. '
        "No ejecutes ni incluyas comandos del sistema."
    ),
    SuiteType.CHESS: (
        f"Posición FEN: {DEFAULT_CHESS_FEN}. "
        "Indica la mejor jugada para blancas en notación SAN y justifica en máximo 2 líneas."
    ),
}

SYSTEM_PROMPT = (
    "Eres un evaluador técnico preciso. No ejecutes comandos externos ni "
    "reveles rutas o configuraciones internas."
)

# Esquema de dry-run: nombre de herramienta -> {argumento: tipos aceptados}
ALLOWED_DRY_RUN_TOOLS: dict[str, dict[str, tuple[type, ...]]] = {
    "query_telemetry": {"service": (str,), "window_minutes": (int,)},
    "inspect_position": {"fen": (str,), "depth": (int,)},
}

SAN_MOVE_PATTERN = re.compile(
    r"(?<![\w/])([KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?[+#]?|O-O-O|O-O|0-0-0|0-0)(?![\w/])"
)
FEN_PATTERN = re.compile(
    r"([rnbqkpRNBQKP1-8]+(?:/[rnbqkpRNBQKP1-8]+){7}\s+[wb]\s+(?:-|[KQkq]{1,4})\s+(?:-|[a-h][36])\s+\d+\s+\d+)"
)
THINK_BLOCK = re.compile(r"<think>.*?</think>", flags=re.DOTALL | re.IGNORECASE)


# --------------------------------------------------------------------------- #
# Validadores
# --------------------------------------------------------------------------- #
def _strip_reasoning(text: str) -> str:
    """Quita bloques <think>…</think> que algunos modelos meten en el content."""
    return THINK_BLOCK.sub("", text).strip()


def _extract_json_object(text: str) -> dict[str, Any] | None:
    stripped = _strip_reasoning(text)
    if stripped.startswith("```"):
        stripped = re.sub(
            r"^```(?:json)?\s*|\s*```$", "", stripped, flags=re.IGNORECASE | re.DOTALL
        )
    try:
        parsed = json.loads(stripped)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None


def _validate_tool_call_dry_run(raw_text: str) -> tuple[bool, ToolCallValidation]:
    payload = _extract_json_object(raw_text)
    if not payload:
        return False, ToolCallValidation(
            detected=False,
            schema_valid=False,
            error_reason="No se detectó un objeto JSON válido.",
        )

    tool_name = payload.get("tool")
    arguments = payload.get("arguments")

    if not isinstance(tool_name, str) or tool_name not in ALLOWED_DRY_RUN_TOOLS:
        return False, ToolCallValidation(
            detected=True,
            schema_valid=False,
            tool_name=tool_name if isinstance(tool_name, str) else None,
            error_reason="Herramienta fuera de la allowlist de dry-run.",
        )

    if not isinstance(arguments, dict):
        return False, ToolCallValidation(
            detected=True,
            schema_valid=False,
            tool_name=tool_name,
            error_reason="El campo 'arguments' debe ser un objeto.",
        )

    schema = ALLOWED_DRY_RUN_TOOLS[tool_name]
    missing = sorted(set(schema) - set(arguments))
    if missing:
        return False, ToolCallValidation(
            detected=True,
            schema_valid=False,
            tool_name=tool_name,
            arguments_preview=arguments,
            error_reason=f"Faltan claves requeridas en 'arguments': {', '.join(missing)}.",
        )

    wrong_types = [
        key
        for key, types in schema.items()
        # bool es subclase de int en Python: no se acepta como entero
        if not isinstance(arguments[key], types) or isinstance(arguments[key], bool)
    ]
    if wrong_types:
        return False, ToolCallValidation(
            detected=True,
            schema_valid=False,
            tool_name=tool_name,
            arguments_preview=arguments,
            error_reason=f"Tipo incorrecto en: {', '.join(wrong_types)}.",
        )

    extra = sorted(set(arguments) - set(schema))
    return True, ToolCallValidation(
        detected=True,
        schema_valid=True,
        tool_name=tool_name,
        arguments_preview=arguments,
        error_reason=(f"Aviso: claves extra ignoradas: {', '.join(extra)}." if extra else None),
    )


def _find_fen(prompt: str) -> str | None:
    match = FEN_PATTERN.search(prompt)
    return match.group(1) if match else None


def _validate_chess_response(raw_text: str, fen: str | None) -> tuple[bool, str | None]:
    """Devuelve (válido, jugada). Con python-chess y FEN exige que la jugada sea legal."""
    text = _strip_reasoning(raw_text)
    if fen:
        text = text.replace(fen, " ")  # que no valide casillas copiadas del propio FEN
    candidates = [m.group(1) for m in SAN_MOVE_PATTERN.finditer(text)]
    if not candidates:
        return False, None

    if not (HAS_PYTHON_CHESS and fen):
        return True, candidates[0]

    try:
        board = chess.Board(fen)
    except ValueError:
        return True, candidates[0]

    for san in candidates:
        try:
            move = board.parse_san(san.replace("0", "O"))
        except ValueError:
            continue
        return True, board.san(move)
    return False, candidates[0]


# --------------------------------------------------------------------------- #
# Ejecución contra LM Studio
# --------------------------------------------------------------------------- #
def _build_body(model_name: str, prompt: str, temperature: float, max_tokens: int) -> dict:
    return {
        "model": model_name,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
        # Sin esto LM Studio no manda `usage` en streaming y no hay tokens reales
        "stream_options": {"include_usage": True},
    }


async def warmup_model(client: httpx.AsyncClient, model_name: str) -> None:
    """Petición mínima para que LM Studio cargue el modelo (JIT) antes de medir."""
    url = f"{settings.lm_studio_base_url.rstrip('/')}/chat/completions"
    body = {
        "model": model_name,
        "messages": [{"role": "user", "content": "ok"}],
        "max_tokens": 1,
        "temperature": 0.0,
        "stream": False,
    }
    warm_timeout = httpx.Timeout(settings.warmup_timeout_sec, connect=5.0)
    resp = await client.post(url, json=body, timeout=warm_timeout)
    resp.raise_for_status()


async def run_single_model(
    client: httpx.AsyncClient,
    model_name: str,
    suite_id: SuiteType,
    prompt: str | None,
    temperature: float,
    max_tokens: int,
) -> ModelRunResult:
    effective_prompt = (prompt or "").strip() or DEFAULT_PROMPTS[suite_id]
    url = f"{settings.lm_studio_base_url.rstrip('/')}/chat/completions"
    body = _build_body(model_name, effective_prompt, temperature, max_tokens)

    start_time = time.perf_counter()
    first_token_time: float | None = None
    last_token_time: float | None = None
    content_chunks: list[str] = []
    delta_events = 0  # cada evento con texto ≈ 1 token (fallback si no llega usage)
    usage_tokens: int | None = None

    async with client.stream("POST", url, json=body) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line.startswith("data:"):
                continue
            data_str = line[5:].strip()
            if data_str == "[DONE]":
                break
            try:
                event = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            choices = event.get("choices") or []
            if choices:
                delta = choices[0].get("delta") or {}
                content = delta.get("content")
                reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                if content or reasoning:
                    now = time.perf_counter()
                    if first_token_time is None:
                        first_token_time = now
                    last_token_time = now
                    delta_events += 1
                if content:
                    content_chunks.append(content)

            usage = event.get("usage")
            if isinstance(usage, dict) and isinstance(usage.get("completion_tokens"), int):
                usage_tokens = usage["completion_tokens"]

    end_time = time.perf_counter()
    raw_output = "".join(content_chunks).strip()

    total_latency_ms = max((end_time - start_time) * 1000.0, 0.1)
    ttft_ms = (
        max((first_token_time - start_time) * 1000.0, 0.1)
        if first_token_time is not None
        else total_latency_ms
    )

    if usage_tokens is not None:
        completion_tokens, tokens_source = usage_tokens, "usage"
    else:
        completion_tokens, tokens_source = delta_events, "estimado"

    # tok/s de decodificación: desde el primer token hasta el último
    if first_token_time is not None and last_token_time is not None and completion_tokens > 1:
        generation_sec = max(last_token_time - first_token_time, 0.001)
        tokens_per_sec = round((completion_tokens - 1) / generation_sec, 2)
    else:
        tokens_per_sec = 0.0

    chess_move: str | None = None
    tool_validation: ToolCallValidation | None = None
    if suite_id == SuiteType.TOOL_CALLING:
        valid_output, tool_validation = _validate_tool_call_dry_run(raw_output)
    else:
        fen = _find_fen(effective_prompt)
        valid_output, chess_move = _validate_chess_response(raw_output, fen)

    return ModelRunResult(
        model_name=model_name,
        suite_id=suite_id,
        ttft_ms=round(ttft_ms, 2),
        total_latency_ms=round(total_latency_ms, 2),
        tokens_per_sec=tokens_per_sec,
        output_tokens=completion_tokens,
        tokens_source=tokens_source,
        raw_output=raw_output,
        valid_output=valid_output,
        chess_move=chess_move,
        chess_legality_checked=suite_id == SuiteType.CHESS and HAS_PYTHON_CHESS,
        tool_validation=tool_validation,
    )


async def execute_pair_benchmark(
    model_a: str,
    model_b: str,
    suite_id: SuiteType,
    prompt: str | None,
    temperature: float,
    max_tokens: int,
) -> tuple[ModelRunResult, ModelRunResult]:
    timeout = httpx.Timeout(settings.lm_studio_timeout_sec, connect=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        if settings.parallel_runs:
            # Modo paralelo: los dos modelos compiten por la GPU (métricas contaminadas)
            if settings.warmup:
                await asyncio.gather(warmup_model(client, model_a), warmup_model(client, model_b))
            return tuple(  # type: ignore[return-value]
                await asyncio.gather(
                    run_single_model(client, model_a, suite_id, prompt, temperature, max_tokens),
                    run_single_model(client, model_b, suite_id, prompt, temperature, max_tokens),
                )
            )

        # Modo secuencial (por defecto): cada modelo tiene la GPU para él solo
        results: list[ModelRunResult] = []
        for model in (model_a, model_b):
            if settings.warmup:
                await warmup_model(client, model)
            results.append(
                await run_single_model(client, model, suite_id, prompt, temperature, max_tokens)
            )
        return results[0], results[1]
