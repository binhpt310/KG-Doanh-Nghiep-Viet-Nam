import os
import re
import threading

import requests
from dotenv import load_dotenv
from llmware.configs import LLMWareConfig
from llmware.gguf_configs import GGUFConfigs
from llmware.models import ModelCatalog
from neo4j import GraphDatabase


load_dotenv()


def _detect_gpu() -> bool:
    return os.path.exists("/proc/driver/nvidia/version") and os.path.exists("/dev/nvidia0")


USE_GPU = _detect_gpu()
if USE_GPU:
    try:
        GGUFConfigs().set_config("force_gpu", True)
        GGUFConfigs().set_config("n_gpu_layers", 100)
    except Exception as gpu_error:
        print(f"[GPU] GGUF config error (ignored): {gpu_error}")
else:
    print("[GPU] No GPU detected. Falling back to CPU inference.")


LLMWareConfig().set_active_db("sqlite")
LLMWareConfig().set_vector_db("chromadb")


BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DOCS_DIR = os.path.join(BASE_DIR, "docs")
ENV_DOCKER_PATH = os.path.join(BASE_DIR, ".env.docker")
RAG_LIBRARY_NAME = "kg_demo_vn"


NEO4J_URI = os.getenv("NEO4J_URI", "neo4j://localhost:7687")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password123")
if NEO4J_URI.startswith("neo4j://"):
    NEO4J_URI = "bolt://" + NEO4J_URI[len("neo4j://") :]
neo4j_driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))


LLM_INFERENCE_TIMEOUT = int(os.getenv("LLM_INFERENCE_TIMEOUT", "300"))
OLLAMA_NUM_CTX = 10000
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "8192"))
LIVE_NEWS_TIMEOUT = float(os.getenv("LIVE_NEWS_TIMEOUT", "4.0"))
LIVE_NEWS_MAX_ITEMS = int(os.getenv("LIVE_NEWS_MAX_ITEMS", "5"))

ALLOWED_LLM_BACKENDS = frozenset({"openai", "vllm", "openai_compat", "ollama"})
THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _default_llm_base(backend: str) -> str:
    return "http://localhost:9061" if backend in ("openai", "vllm", "openai_compat") else "http://localhost:11434"


MODEL_NAME = os.getenv("MODEL_NAME", "qwen3-14b").strip()
LLM_BACKEND = os.getenv("LLM_BACKEND", "openai").strip().lower()
LLM_BASE_URL = (os.getenv("LLM_BASE_URL") or os.getenv("VLLM_BASE_URL") or _default_llm_base(LLM_BACKEND)).strip()
if not LLM_BASE_URL.startswith("http"):
    LLM_BASE_URL = f"http://{LLM_BASE_URL}"
LLM_BASE_URL = LLM_BASE_URL.rstrip("/")
os.environ["LLM_BASE_URL"] = LLM_BASE_URL
LLM_API_KEY = (os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY") or "").strip()

LLM_HTTP_HOST = ""
LLM_HTTP_PORT = 0


def sync_llm_parsed_port() -> None:
    """Refresh the parsed host/port after runtime settings are changed."""
    global LLM_HTTP_HOST, LLM_HTTP_PORT
    parsed = LLM_BASE_URL.replace("http://", "").replace("https://", "").rstrip("/").split(":")
    LLM_HTTP_HOST = parsed[0]
    LLM_HTTP_PORT = int(parsed[1]) if len(parsed) > 1 else (
        9061 if LLM_BACKEND in ("openai", "vllm", "openai_compat") else 11434
    )


sync_llm_parsed_port()


def mask_api_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 4:
        return "****"
    return "***" + key[-4:]


def write_env_docker_kv(updates: dict[str, str], remove_keys: set | None = None) -> None:
    """Merge runtime settings into `.env.docker` without disturbing unrelated lines."""
    remove_keys = set(remove_keys or [])
    lines: list[str] = []
    if os.path.isfile(ENV_DOCKER_PATH):
        with open(ENV_DOCKER_PATH, "r", encoding="utf-8") as file_handle:
            lines = file_handle.read().splitlines()

    seen_update = {key: False for key in updates}
    output: list[str] = []
    for line in lines:
        if not line.strip() or line.strip().startswith("#") or "=" not in line:
            output.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in remove_keys:
            continue
        if key in updates:
            output.append(f"{key}={updates[key]}")
            seen_update[key] = True
        else:
            output.append(line)

    for key, value in updates.items():
        if not seen_update.get(key):
            output.append(f"{key}={value}")

    tmp_path = ENV_DOCKER_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as file_handle:
        file_handle.write("\n".join(output) + "\n")
    os.replace(tmp_path, ENV_DOCKER_PATH)


def strip_think_tags(text: str) -> str:
    return THINK_RE.sub("", text).strip()


def fetch_remote_models(
    *,
    base_url: str | None = None,
    backend: str | None = None,
    api_key: str | None = None,
    fallback_model: str | None = None,
) -> list[str]:
    """Fetch models from the active runtime or an explicitly provided backend/base URL."""
    backend = (backend or LLM_BACKEND).strip().lower()
    base_url = (base_url or LLM_BASE_URL).strip().rstrip("/")
    api_key = (api_key if api_key is not None else LLM_API_KEY).strip()
    fallback_model = (fallback_model or MODEL_NAME).strip()

    models: list[str] = []
    try:
        if backend in ("openai", "vllm", "openai_compat"):
            headers = {}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            response = requests.get(f"{base_url}/v1/models", headers=headers, timeout=8)
            response.raise_for_status()
            models = [model["id"] for model in response.json().get("data", []) if model.get("id")]
        else:
            response = requests.get(f"{base_url}/api/tags", timeout=8)
            response.raise_for_status()
            models = [model["name"] for model in response.json().get("models", []) if model.get("name")]
    except Exception as ex:
        print(f"[LLM] models list error: {ex}")
        models = []

    return models or ([fallback_model] if fallback_model else [])


def ollama_inference(prompt: str, model: str | None = None) -> dict:
    model = (model or MODEL_NAME).strip()
    response = requests.post(
        f"{LLM_BASE_URL}/api/chat",
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt.strip() + "/nothink"}],
            "stream": False,
            "keep_alive": -1,
            "options": {"temperature": 0.8, "num_ctx": OLLAMA_NUM_CTX},
        },
        timeout=LLM_INFERENCE_TIMEOUT,
    )
    response.raise_for_status()
    body = response.json()
    text = strip_think_tags(body.get("message", {}).get("content", ""))
    return {"llm_response": text.strip(), "usage": {}}


def openai_compatible_inference(prompt: str, model: str | None = None) -> dict:
    model = (model or MODEL_NAME).strip()
    headers = {"Content-Type": "application/json"}
    if LLM_API_KEY:
        headers["Authorization"] = f"Bearer {LLM_API_KEY}"
    response = requests.post(
        f"{LLM_BASE_URL}/v1/chat/completions",
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt.strip()}],
            "temperature": 0.8,
            "max_tokens": LLM_MAX_TOKENS,
            "stream": False,
        },
        headers=headers,
        timeout=LLM_INFERENCE_TIMEOUT,
    )
    response.raise_for_status()
    body = response.json()
    choices = body.get("choices") or []
    text = ""
    if choices and isinstance(choices[0], dict):
        text = (choices[0].get("message") or {}).get("content") or ""
    return {"llm_response": strip_think_tags(text).strip(), "usage": body.get("usage") or {}}


def llm_inference(prompt: str, model: str | None = None) -> dict:
    if LLM_BACKEND in ("openai", "vllm", "openai_compat"):
        return openai_compatible_inference(prompt, model=model)
    return ollama_inference(prompt, model=model)


def _keep_alive() -> None:
    if LLM_BACKEND != "ollama":
        return
    try:
        requests.post(
            f"{LLM_BASE_URL}/api/chat",
            json={
                "model": MODEL_NAME,
                "messages": [{"role": "user", "content": "ping"}],
                "stream": False,
                "keep_alive": -1,
                "options": {"num_ctx": OLLAMA_NUM_CTX},
            },
            timeout=120,
        )
    except Exception as ex:
        print(f"[LLM] keep_alive skipped: {ex}")


def register_active_model() -> None:
    if LLM_BACKEND == "ollama":
        ModelCatalog().register_ollama_model(
            model_name=MODEL_NAME,
            model_type="chat",
            host=LLM_HTTP_HOST,
            port=LLM_HTTP_PORT,
            temperature=0.8,
            context_window=10000,
        )
    else:
        print(f"[LLM] backend={LLM_BACKEND} base={LLM_BASE_URL} model={MODEL_NAME}")


def update_llm_runtime(
    *,
    backend: str,
    base_url: str,
    model: str,
    api_key: str | None = None,
    clear_api_key: bool = False,
) -> dict:
    """Apply runtime settings in-memory and persist them back to `.env.docker`."""
    global MODEL_NAME, LLM_BACKEND, LLM_BASE_URL, LLM_API_KEY

    next_backend = backend.strip().lower()
    if next_backend not in ALLOWED_LLM_BACKENDS:
        raise ValueError(f"LLM_BACKEND không hợp lệ: {next_backend}")

    next_base_url = base_url.strip().rstrip("/")
    if next_base_url and not next_base_url.startswith("http"):
        next_base_url = f"http://{next_base_url}"
    if not next_base_url:
        next_base_url = _default_llm_base(next_backend)

    next_model = model.strip()
    if not next_model:
        raise ValueError("MODEL_NAME rỗng")

    key_changed = False
    next_api_key = LLM_API_KEY
    if clear_api_key:
        next_api_key = ""
        key_changed = True
    elif api_key is not None and api_key.strip():
        next_api_key = api_key.strip()
        key_changed = True

    LLM_BACKEND = next_backend
    LLM_BASE_URL = next_base_url
    MODEL_NAME = next_model
    if key_changed:
        LLM_API_KEY = next_api_key

    os.environ["LLM_BASE_URL"] = LLM_BASE_URL
    os.environ["OPENAI_API_KEY"] = LLM_API_KEY
    os.environ["LLM_API_KEY"] = LLM_API_KEY
    sync_llm_parsed_port()
    register_active_model()

    updates = {
        "LLM_BACKEND": LLM_BACKEND,
        "LLM_BASE_URL": LLM_BASE_URL,
        "VLLM_BASE_URL": LLM_BASE_URL,
        "MODEL_NAME": MODEL_NAME,
    }
    remove_keys: set[str] = set()
    if key_changed:
        if LLM_API_KEY:
            updates["OPENAI_API_KEY"] = LLM_API_KEY
        else:
            remove_keys.update({"OPENAI_API_KEY", "LLM_API_KEY"})

    write_env_docker_kv(updates, remove_keys=remove_keys)
    return {
        "backend": LLM_BACKEND,
        "base_url": LLM_BASE_URL,
        "model": MODEL_NAME,
        "models": fetch_remote_models(),
        "api_key_masked": mask_api_key(LLM_API_KEY),
    }


threading.Thread(target=_keep_alive, daemon=True).start()
register_active_model()
