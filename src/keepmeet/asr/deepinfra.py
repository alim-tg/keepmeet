import logging
import time

import requests

logger = logging.getLogger(__name__)

API_URL = "https://api.deepinfra.com/v1/inference/openai/{model}"
RETRY_STATUSES = {408, 429, 500, 502, 503, 504}
ATTEMPTS = 4
MODELS_WITHOUT_PROMPT = {"whisper-large-v3-turbo"}


class AsrError(Exception):
    pass


def _normalize(data: dict | None) -> dict:
    data = dict(data or {})
    segments = []
    for seg in data.get("segments") or []:
        seg = dict(seg)
        seg["text"] = seg.get("text") or ""
        segments.append(seg)
    words = []
    for w in data.get("words") or []:
        raw = w.get("word") or w.get("text") or ""
        if raw.strip() and w.get("start") is not None:
            words.append({
                "word": raw.strip(),
                "raw": raw,
                "start": float(w["start"]),
                "end": float(w.get("end") or w["start"]),
            })
    return {
        "segments": segments,
        "words": words,
        "score": _confidence(segments),
        "language": data.get("language"),
        "cost": (data.get("inference_status") or {}).get("cost"),
    }


def _confidence(segments: list[dict]) -> float:
    scored = [(s["avg_logprob"], len(s.get("tokens") or [0]) or 1) for s in segments if s.get("avg_logprob") is not None]
    if not scored:
        return float("-inf")
    return sum(lp * n for lp, n in scored) / sum(n for _, n in scored)


def _post(wav: bytes, api_key: str, model: str, params: dict) -> dict:
    last_error = None
    for attempt in range(ATTEMPTS):
        try:
            resp = requests.post(
                API_URL.format(model=model),
                headers={"Authorization": f"bearer {api_key}"},
                files={"audio": ("chunk.wav", wav, "audio/wav")},
                data=params,
                timeout=600,
            )
        except requests.RequestException as e:
            last_error = str(e)
        else:
            if resp.status_code == 200:
                return _normalize(resp.json())
            last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
            if resp.status_code not in RETRY_STATUSES:
                break
        if attempt < ATTEMPTS - 1:
            delay = 2 ** attempt * 3
            logger.warning("DeepInfra request failed (%s), retrying in %ss", last_error, delay)
            time.sleep(delay)
    raise AsrError(f"DeepInfra transcription failed: {last_error}")


def transcribe(wav: bytes, api_key: str, model: str, language: str, prompt: str | None) -> dict:
    params = {"chunk_level": "word", "language": language}
    use_prompt = bool(prompt) and model not in MODELS_WITHOUT_PROMPT
    if use_prompt:
        params["initial_prompt"] = prompt
    result = _post(wav, api_key, model, params)
    if use_prompt and not result["words"]:
        logger.warning("Empty transcription with prompt, retrying without it")
        params.pop("initial_prompt")
        result = _post(wav, api_key, model, params)
    return result
