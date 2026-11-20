# Guía de operación — Vertex Model Benchmark Arena

## 1. De qué trata este proyecto

**Vertex Model Benchmark Arena** es una plataforma para comparar lado a lado modelos locales servidos desde **LM Studio** (o cualquier endpoint compatible con OpenAI en `http://localhost:1234/v1`), construida para **Vertex Coders LLC** en `E:\vertex-model-bench`.

### Qué resuelve

* **Comparación justa entre modelos locales:** enfrenta dos modelos (por ejemplo `vertex-nemotron-core-4b` contra `vertex-gemma-2b-mcp`) y mide **TTFT** (ms), **latencia total** (ms), **velocidad** (tok/s de decodificación) y **tokens generados**. Por defecto corre A y luego B, con warmup previo, para que la GPU no se reparta y la carga del modelo no ensucie el TTFT.
* **Tool-Calling en dry-run:** comprueba que el modelo respete el esquema (`tool` + `arguments`) contra una allowlist (`query_telemetry`, `inspect_position`), con claves y tipos correctos. Devuelve `tool_name`, `arguments_preview` y `error_reason` sin ejecutar nada.
* **Ajedrez (SAN):** sobre una posición FEN, extrae la jugada propuesta y, con `python-chess` instalado, verifica que sea legal.
* **Stack:**
  * **Backend (`vertex-model-bench-api`):** FastAPI + Pydantic v2 + `httpx` asíncrono en `127.0.0.1:8015`, CORS acotado a `4200` y errores sin trazas internas.
  * **Frontend (`vertex-model-bench-ui`):** Angular 21 (standalone, Signals, OnPush) + **Angular Material 3** en tema oscuro, responsive desde `360px`.

---

## 2. Cómo usar el Benchmark Arena

### Paso 1: Preparar LM Studio

1. Abre **LM Studio** e inicia el servidor local en `http://localhost:1234`.
2. No hace falta cargar los modelos a mano: el backend los precalienta (JIT) antes de medir. Eso sí, con la 1660 Ti un modelo de 4B tiene que caber en la VRAM. Si LM Studio no puede cargarlo, la UI muestra el error.

### Paso 2: Levantar Backend y Frontend

Desde `E:\vertex-model-bench`:

```powershell
.\start-bench.ps1
```

El script comprueba antes de arrancar:

* que exista el `.venv` y `node_modules`;
* que LM Studio responda;
* que los puertos `8015` y `4200` estén libres. Si alguno ya está ocupado, avisa y no abre otra ventana encima.

Luego:

1. Verifica `http://127.0.0.1:8015/health`. Debe decir `"status":"ok"`, el modo y si la legalidad de ajedrez está activa.
2. Abre `http://127.0.0.1:4200`.

*(Si PowerShell bloquea scripts locales: `powershell -ExecutionPolicy Bypass -File .\start-bench.ps1`, desde la misma carpeta.)*

### Paso 3: Ejecutar pruebas y leer resultados

1. Elige **Modelo A** y **Modelo B**. La lista viene de LM Studio, sin modelos de embeddings ni de imagen. El botón ⟳ la recarga.
2. Pulsa **Run Tool-Calling** o **Run Chess**:
   * mientras corre se ve la barra de progreso y los controles quedan bloqueados;
   * al terminar, el chip de arriba marca el modo usado y el modelo con más tok/s.
3. En cada tarjeta revisa:
   * **TTFT**, **Velocidad**, **Latencia total**;
   * **Tokens**: si dice *(estimado)*, LM Studio no mandó el conteo real;
   * **Esquema** (tool-calling) o **Jugada** (ajedrez): `LEGAL: Ng5`, `ILEGAL (Qh5)` o `SIN JUGADA`;
   * el **Tool-Calling Dry-Run Inspector** y la salida cruda.

---

## 3. Ajustes (`vertex-model-bench-api\.env`, opcional)

```ini
WARMUP=true
PARALLEL_RUNS=false
LM_STUDIO_TIMEOUT_SEC=120
WARMUP_TIMEOUT_SEC=180
```

Después de cambiar el `.env`, reinicia la ventana de la API (Ctrl+C y vuelve a correr `start-bench.ps1`).
