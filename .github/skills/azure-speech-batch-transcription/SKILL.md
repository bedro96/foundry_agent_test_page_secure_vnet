---
name: azure-speech-batch-transcription
display_name: Azure Speech Batch Transcription
description: >-
    Transcribe Telegram voice messages using Azure Speech batch transcription REST API v3.2.
    No SDK, no external blob storage. Audio served from in-memory vault, authenticated via
    DefaultAzureCredential, with ffmpeg conversion and automatic cleanup.
user-invocable: true
---

# Skill: Azure Speech Batch Transcription

## 1. Purpose

Transcribe Telegram voice messages (or any short audio) into text using the **Azure Speech batch transcription REST API v3.2** — no Azure SDK, no external blob storage. Audio bytes are served temporarily by the backend's own public HTTP endpoint and cleaned up immediately after the transcription job finishes.

Key design goals:
- **No external storage** — audio lives in an in-memory vault keyed by a UUID token.
- **No Azure Speech SDK** — every call is plain HTTPS via `aiohttp`.
- **DefaultAzureCredential** — no API keys; uses managed identity or service principal automatically.
- **Clean up on every exit path** — vault entry and batch job are deleted in `finally`.

---

## 2. When to Use

Use this skill when **all** of the following are true:

| Condition | Why it matters |
|---|---|
| Endpoint is an **Azure AI Foundry hub** (`*.services.ai.azure.com`) | Foundry hubs expose `/speechtotext/v3.2/` only — the real-time REST endpoint (`/speech/recognition/…`) is not available. |
| Audio is short enough to hold in memory | Vault stores bytes in-process; large files (> 10 MB) are rejected. |
| No external storage (Blob, ADLS, etc.) is available or wanted | The backend serves audio directly over its own public URL. |
| Latency of ~5–120 s is acceptable | Batch jobs poll every 3 s for up to 120 s. |

**Do NOT use** when:
- You need sub-second streaming transcription — use Azure Speech SDK real-time instead.
- The backend is not publicly reachable by Azure Speech — the batch job cannot download the audio URL.
- Audio files exceed 10 MB — reject at the intake layer.

---

## 3. Architecture

```
Telegram voice message (OGG/OPUS/MP3/M4A/WAV bytes)
        │
        ▼
_convert_audio_bytes_to_wav()          ← blocking, run in asyncio.to_thread()
  - imageio_ffmpeg.get_ffmpeg_exe()
  - ffmpeg: -acodec pcm_s16le -ac 1 -ar 16000
  - writes input.<ext> and reads output.wav from TemporaryDirectory
        │
        ▼  wav_bytes (16 kHz, mono, PCM)
        │
        ▼
vault_store(wav_bytes) → token (UUID)
        │  _audio_vault[token] = wav_bytes  (thread-safe, threading.Lock)
        │
        ▼
audio_url = f"{BACKEND_PUBLIC_URL}/audio/{token}"
        │
        ▼
POST /speechtotext/v3.2/transcriptions    ← Azure Speech batch API
  {
    "contentUrls": ["https://<backend>/audio/<token>"],
    "locale": "ko-KR",
    "displayName": "telegram-<token[:8]>"
  }
  → 201  +  {"self": "…/transcriptions/<job_id>"}
        │
        ▼
Azure Speech downloads audio from backend URL
  GET /audio/<token>  →  wav_bytes  (served by FastAPI route)
        │
        ▼  (poll every 3 s, max 40 polls = ~120 s)
GET /speechtotext/v3.2/transcriptions/<job_id>
  → {"status": "Running"|"Succeeded"|"Failed"}
        │
        ▼ (on Succeeded)
GET /speechtotext/v3.2/transcriptions/<job_id>/files
  → values[].kind == "Transcription" → links.contentUrl
        │
        ▼
GET <contentUrl>  →  result JSON
  _extract_batch_transcript(result)
  → combinedRecognizedPhrases[].display   (primary)
  → recognizedPhrases[].nBest[0].display  (fallback)
        │
        ▼
transcript (str)
        │
finally block (always runs):
  vault_remove(token)            ← clears in-memory audio
  DELETE /speechtotext/v3.2/transcriptions/<job_id>   ← cleans up batch job
```

### Audio serving route

The backend exposes a thin unauthenticated route that serves vault bytes:

```
GET /audio/{token}
```

The token itself acts as the secret — it is a random UUID never shown to end users, only embedded in the batch job `contentUrls`. The entry is removed immediately after the batch job finishes.

---

## 4. Key Concepts with Code

### 4.1 In-Memory Audio Vault

```python
_audio_vault: dict[str, bytes] = {}
_audio_vault_lock = threading.Lock()

def vault_store(wav_bytes: bytes) -> str:
    """Store WAV bytes; return a one-time UUID token."""
    token = str(uuid.uuid4())
    with _audio_vault_lock:
        _audio_vault[token] = wav_bytes
    return token

def vault_get(token: str) -> bytes | None:
    """Retrieve bytes for the HTTP serve route."""
    with _audio_vault_lock:
        return _audio_vault.get(token)

def vault_remove(token: str) -> None:
    """Delete vault entry after the batch job finishes."""
    with _audio_vault_lock:
        _audio_vault.pop(token, None)
```

`threading.Lock` is used (not `asyncio.Lock`) because `vault_get` may be called from a synchronous WSGI/ASGI handler thread.

### 4.2 DefaultAzureCredential Bearer Token

```python
from azure.identity.aio import DefaultAzureCredential

async def _get_bearer_token(self) -> str:
    async with DefaultAzureCredential() as credential:
        token = await credential.get_token("https://cognitiveservices.azure.com/.default")
    return token.token
```

The token is fetched once per transcription call and attached to all batch API requests:

```python
headers = {
    "Authorization": f"Bearer {bearer_token}",
    "Content-Type": "application/json",
}
```

### 4.3 Submitting the Batch Job

```python
_BATCH_PATH = "/speechtotext/v3.2/transcriptions"

body = {
    "contentUrls": [audio_url],          # public URL to the WAV in the vault
    "locale": language,                  # e.g. "ko-KR", "en-US"
    "displayName": f"telegram-{token[:8]}",
}

async with sess.post(f"{base_url}{_BATCH_PATH}", headers=headers, data=json.dumps(body)) as r:
    if r.status != 201:
        raise RuntimeError(f"Batch job creation failed: {r.status}")
    job = json.loads(await r.text())
    job_id  = job["self"].split("/")[-1]
    job_url = f"{base_url}{_BATCH_PATH}/{job_id}"
```

- Expected status: **201 Created**
- The `job["self"]` URL contains the full canonical job URL; split on `/` to get the `job_id`.

### 4.4 Polling

```python
_BATCH_POLL_INTERVAL_SECS = 3
_BATCH_MAX_POLLS = 40  # ~120 s maximum

for poll_num in range(_BATCH_MAX_POLLS):
    await asyncio.sleep(_BATCH_POLL_INTERVAL_SECS)
    async with sess.get(job_url, headers=headers) as r:
        status_body = await r.json()
        status = status_body.get("status")

    if status == "Succeeded":
        # fetch files and extract transcript
        break
    elif status == "Failed":
        err = status_body.get("properties", {}).get("error", {})
        raise RuntimeError(f"Batch transcription failed: {json.dumps(err)[:200]}")
else:
    raise RuntimeError("Batch transcription timed out after 120 seconds.")
```

The `for…else` pattern raises if the loop exhausts without hitting `break`.

### 4.5 Fetching the Result

```python
async with sess.get(f"{job_url}/files", headers=headers) as r:
    files_body = await r.json()

for f_item in files_body.get("values", []):
    if f_item.get("kind") == "Transcription":
        async with sess.get(f_item["links"]["contentUrl"]) as tr:
            result_body = await tr.json()
        transcript = _extract_batch_transcript(result_body)
```

The files endpoint returns a list; only items with `kind == "Transcription"` contain the result JSON. The `contentUrl` is a pre-signed URL — **no Authorization header needed**.

### 4.6 Transcript Extraction

```python
def _extract_batch_transcript(result: dict[str, Any]) -> str | None:
    # Primary: combinedRecognizedPhrases[].display (full-text summary)
    combined = result.get("combinedRecognizedPhrases", [])
    for phrase in combined:
        text = (phrase.get("display") or "").strip()
        if text:
            return text

    # Fallback: join recognizedPhrases[].nBest[0].display (per-segment)
    phrases = result.get("recognizedPhrases", [])
    segments: list[str] = []
    for phrase in phrases:
        nbest = phrase.get("nBest", [])
        if nbest:
            display = (nbest[0].get("display") or "").strip()
            if display:
                segments.append(display)
    return " ".join(segments) if segments else None
```

Note: batch API uses **lowercase keys** (`display`, `nBest`) unlike the real-time API (`Display`, `NBest`).

### 4.7 ffmpeg Conversion

```python
import imageio_ffmpeg

extension = _resolve_audio_extension(mime_type, file_name)  # ".ogg", ".mp3", etc.

with TemporaryDirectory(prefix="telegram-voice-") as temp_dir:
    input_path  = Path(temp_dir) / f"input{extension}"
    output_path = Path(temp_dir) / "output.wav"
    input_path.write_bytes(audio_bytes)

    result = subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-y", "-i", str(input_path),
            "-vn",                     # no video
            "-acodec", "pcm_s16le",   # 16-bit signed little-endian PCM
            "-ac", "1",               # mono
            "-ar", "16000",           # 16 kHz sample rate
            str(output_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not output_path.exists():
        raise RuntimeError(f"ffmpeg failed: {result.stderr[-500:]}")

    return output_path.read_bytes()
```

This runs synchronously in a thread pool via `asyncio.to_thread(self._convert_audio_bytes_to_wav, ...)` to avoid blocking the event loop.

### 4.8 Audio Extension Resolution

```python
def _resolve_audio_extension(mime_type: str, file_name: str | None) -> str:
    suffix = Path(file_name or "").suffix.lower()
    if suffix in {".ogg", ".oga", ".opus", ".wav", ".mp3", ".m4a"}:
        return suffix

    normalized_mime = mime_type.strip().lower()
    if normalized_mime in {"audio/ogg", "application/ogg", "audio/opus"}:
        return ".ogg"
    if normalized_mime in {"audio/wav", "audio/x-wav", "audio/wave"}:
        return ".wav"
    if normalized_mime == "audio/mpeg":
        return ".mp3"
    if normalized_mime in {"audio/mp4", "audio/x-m4a"}:
        return ".m4a"
    return ".bin"
```

Telegram voice notes arrive as OGG/OPUS. The extension tells ffmpeg which demuxer to use.

### 4.9 aiohttp Session Timeout

```python
batch_timeout = aiohttp.ClientTimeout(total=180)
async with aiohttp.ClientSession(timeout=batch_timeout) as sess:
    ...
```

180 s total session timeout gives the polling loop (up to ~120 s) plus HTTP overhead room to complete.

---

## 5. Why NOT Real-Time REST

Azure AI Foundry hub endpoints **only** expose the batch transcription API:

```
✅ https://<resource>.services.ai.azure.com/speechtotext/v3.2/transcriptions
❌ https://<resource>.services.ai.azure.com/speech/recognition/conversation/cognitiveservices/v1
```

The real-time REST endpoint (`cognitiveservices/v1`) is available on **classic Cognitive Services** resources only, not on Foundry hubs. Calling it returns 404. If you need real-time transcription on a Foundry resource, use the Azure Speech SDK WebSocket stream instead — but that requires a different credential model.

---

## 6. Environment Variables

| Variable | Required | Description |
|---|---|---|
| `AZURE_SPEECH_ENDPOINT` | ✅ | Azure AI Services base URL, e.g. `https://<resource>.services.ai.azure.com` |
| `BACKEND_PUBLIC_URL` | ✅ | Public base URL of this backend, e.g. `https://bot.example.com` — Azure Speech must be able to reach `GET {BACKEND_PUBLIC_URL}/audio/{token}` |
| `AZURE_CLIENT_ID` | ⚠️ | Service principal client ID (if not using managed identity) |
| `AZURE_TENANT_ID` | ⚠️ | Entra ID tenant ID (if not using managed identity) |
| `AZURE_CLIENT_SECRET` | ⚠️ | Service principal secret (if not using managed identity) |
| `AZURE_SPEECH_LANGUAGE` | optional | BCP-47 locale, default `ko-KR` |

`DefaultAzureCredential` automatically uses managed identity in Azure-hosted environments; set the service principal vars only in local or CI environments.

---

## 7. Error Handling

| Condition | Behavior |
|---|---|
| `audio_bytes` is empty | `RuntimeError("Audio file is empty.")` raised before any I/O |
| `len(audio_bytes) > 10 MB` | `RuntimeError("Audio file is too large to transcribe.")` |
| ffmpeg exits non-zero or output file missing | `RuntimeError` with the last 500 chars of stderr |
| Batch POST returns status ≠ 201 | `RuntimeError` with status code and first 300 chars of response body |
| Batch job `status == "Failed"` | `RuntimeError` with `properties.error` JSON from the status response |
| 40 polls exhausted (≈120 s) without Succeeded/Failed | `RuntimeError("…timed out after 120 seconds.")` |
| Transcript extraction returns `None` | `RuntimeError("…returned no text.")` |
| Cleanup (vault remove / batch DELETE) fails | Logged as `WARNING`; never re-raises — cleanup is best-effort |
| `AZURE_SPEECH_ENDPOINT` not set | `RuntimeError` with actionable message pointing to `.env` |
| `BACKEND_PUBLIC_URL` not set | `RuntimeError` with actionable message |

All cleanup (vault removal + batch job DELETE) runs in a `finally` block, ensuring no vault entries or orphaned batch jobs survive even on error paths.

---

## 8. Do / Don't

### DO

1. **Do set `BACKEND_PUBLIC_URL` to a publicly reachable URL.** Azure Speech downloads the audio from `{BACKEND_PUBLIC_URL}/audio/{token}` — it must be accessible from Azure's network, not localhost.

2. **Do call `vault_remove(token)` and DELETE the batch job in a `finally` block.** The current implementation already does this; preserve it when refactoring.

3. **Do use `asyncio.to_thread()` for the ffmpeg subprocess.** `subprocess.run` is blocking; wrapping it prevents stalling the async event loop.

4. **Do check `kind == "Transcription"` when iterating `/files` response values.** The files endpoint may also return `kind == "TranscriptionReport"` which has a different schema.

5. **Do use `combinedRecognizedPhrases[].display` as the primary extraction target.** It contains the full joined transcript and is more reliable than assembling per-segment phrases.

6. **Do validate audio size before conversion.** The 10 MB limit is checked before ffmpeg runs to avoid wasting CPU and memory on oversized inputs.

### DON'T

1. **Don't call the real-time REST endpoint (`/speech/recognition/…`) on a Foundry hub.** It is not exposed; the request will return 404. Use `/speechtotext/v3.2/transcriptions` (batch) only.

2. **Don't keep vault entries alive longer than necessary.** They hold raw audio bytes in process memory. Always remove them in the `finally` block, even on errors.

3. **Don't authenticate with an API key.** The codebase uses `DefaultAzureCredential` with the `cognitiveservices.azure.com/.default` scope. Mixing API key auth would require different header names and risks accidental key exposure.

4. **Don't fetch a new Bearer token per poll iteration.** The token is fetched once per transcription call and reused across POST, all GET polls, and file retrieval. Fetching per-poll is wasteful and may hit rate limits.

5. **Don't assume the batch result `contentUrl` requires Authorization.** The files endpoint returns pre-signed URLs — send no `Authorization` header when downloading the result JSON, or the request may fail.

6. **Don't skip the `else` clause on the polling `for` loop.** The `for…else` pattern is the timeout guard; removing it means a failed poll loop silently returns `None` instead of raising.
