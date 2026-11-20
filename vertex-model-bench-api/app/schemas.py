from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class SuiteType(str, Enum):
    TOOL_CALLING = "tool-calling"
    CHESS = "chess"


class BenchmarkRequest(BaseModel):
    model_a: str = Field(..., min_length=1, max_length=128)
    model_b: str = Field(..., min_length=1, max_length=128)
    suite_id: SuiteType
    prompt: str | None = Field(default=None, max_length=4000)
    temperature: float = Field(default=0.2, ge=0.0, le=1.5)
    max_tokens: int = Field(default=512, ge=16, le=2048)

    @field_validator("model_a", "model_b")
    @classmethod
    def validate_model_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or any(ch in cleaned for ch in ("\r", "\n", "\x00")):
            raise ValueError("Nombre de modelo inválido.")
        return cleaned


class ToolCallValidation(BaseModel):
    detected: bool = False
    schema_valid: bool = False
    dry_run_safe: bool = True
    tool_name: str | None = None
    arguments_preview: dict[str, Any] = Field(default_factory=dict)
    error_reason: str | None = None


class ModelRunResult(BaseModel):
    model_name: str = Field(..., serialization_alias="modelName")
    suite_id: SuiteType = Field(..., serialization_alias="suiteId")
    ttft_ms: float = Field(..., ge=0.0, serialization_alias="ttftMs")
    total_latency_ms: float = Field(..., ge=0.0, serialization_alias="totalLatencyMs")
    tokens_per_sec: float = Field(..., ge=0.0, serialization_alias="tokensPerSec")
    output_tokens: int = Field(..., ge=0, serialization_alias="outputTokens")
    tokens_source: Literal["usage", "estimado"] = Field(
        default="estimado", serialization_alias="tokensSource"
    )
    raw_output: str = Field(..., serialization_alias="rawOutput")
    valid_output: bool = Field(..., serialization_alias="validOutput")
    chess_move: str | None = Field(default=None, serialization_alias="chessMove")
    chess_legality_checked: bool = Field(
        default=False, serialization_alias="chessLegalityChecked"
    )
    tool_validation: ToolCallValidation | None = Field(
        default=None, serialization_alias="toolValidation"
    )


class PairBenchmarkResponse(BaseModel):
    run_id: str = Field(..., serialization_alias="runId")
    executed_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        serialization_alias="executedAt",
    )
    mode: Literal["secuencial", "paralelo"] = "secuencial"
    left: ModelRunResult
    right: ModelRunResult
