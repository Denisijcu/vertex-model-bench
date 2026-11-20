from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    lm_studio_base_url: str = "http://localhost:1234/v1"
    lm_studio_timeout_sec: float = 120.0
    # Cargar un modelo en JIT en la 1660 Ti puede tardar bastante
    warmup_timeout_sec: float = 180.0
    allowed_origins: list[str] = [
        "http://localhost:4200",
        "http://127.0.0.1:4200",
    ]
    # 1 = una comparación a la vez (las métricas no se pisan entre corridas)
    max_concurrent_runs: int = 1
    # False = modelo A y luego modelo B, cada uno con la GPU solo para él
    parallel_runs: bool = False
    # Petición mínima antes de medir para que el TTFT no incluya la carga del modelo
    warmup: bool = True
    # Modelos que no son de chat y no deben salir en el selector
    excluded_model_keywords: list[str] = ["embed", "imagen"]

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
