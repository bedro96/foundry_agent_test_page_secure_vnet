"""음성-텍스트 변환 헬퍼.

Azure Speech REST v1 API를 사용하여 오디오를 실시간으로 텍스트로 변환합니다.
DefaultAzureCredential → 음성 전용 토큰 발급 → 리전 엔드포인트 호출 방식입니다.

Azure AI Services (kind=AIServices) 리소스의 경우,
REST v1 경로가 리소스 엔드포인트에서 직접 지원되지 않으므로
/sts/v1.0/issuetoken으로 음성 전용 토큰을 발급받은 후
리전 엔드포인트 (https://{region}.stt.speech.microsoft.com)를 사용합니다.
"""

# --- 표준 라이브러리 ---
import asyncio
import base64
import logging
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

# --- 서드파티 라이브러리 ---
import aiohttp
from azure.identity.aio import DefaultAzureCredential

# --- 로컬 모듈 ---
from app.config import Settings

logger = logging.getLogger(__name__)

# 음성 메모는 보통 크기가 작습니다. 10 MB는 여유를 두면서도
# 예상치 못한 대용량 업로드가 과도한 CPU와 메모리를 소비하는 것을 방지합니다.
MAX_AUDIO_BYTES = 10 * 1024 * 1024  # 최대 허용 오디오 크기: 10 MB (10 × 1024 × 1024 바이트)

# REST v1 음성 인식 경로 (단일 발화 인식용, 최대 60초)
_STT_REST_PATH = "/speech/recognition/conversation/cognitiveservices/v1"  # Azure Speech REST v1 대화 인식 엔드포인트 경로


# --- 오디오 형식 헬퍼 --------------------------------------------------------

def _resolve_audio_extension(mime_type: str, file_name: str | None) -> str:
    """오디오 페이로드에 대한 안전한 파일 확장자를 반환합니다.

    Args:
        mime_type: 오디오의 MIME 타입 (예: ``audio/ogg``, ``audio/webm``).
        file_name: 확장자를 추출할 선택적 원본 파일명.

    Returns:
        점을 포함한 소문자 파일 확장자 (예: ``".ogg"``),
        또는 형식을 인식할 수 없는 경우 ``".bin"``.
    """

    # 1단계: 파일명에서 확장자 추출 시도 (가장 신뢰할 수 있는 방법)
    suffix = Path(file_name or "").suffix.lower()
    # 지원되는 오디오 확장자 목록과 일치하면 즉시 반환
    if suffix in {".ogg", ".oga", ".opus", ".wav", ".mp3", ".m4a", ".webm"}:
        return suffix

    # 2단계: MIME 타입 기반 확장자 결정 (파일명이 없거나 확장자를 인식할 수 없는 경우)
    normalized_mime = mime_type.strip().lower()  # MIME 타입 정규화 (공백 제거 및 소문자 변환)
    # WebM 형식 확인 (프론트엔드 마이크 녹음에서 주로 사용)
    if normalized_mime in {"audio/webm", "video/webm"}:
        return ".webm"
    # OGG/Opus 형식 확인 (Telegram 음성 메시지에서 주로 사용)
    if normalized_mime in {"audio/ogg", "application/ogg", "audio/opus"}:
        return ".ogg"
    # WAV 형식 확인 (비압축 PCM 오디오)
    if normalized_mime in {"audio/wav", "audio/x-wav", "audio/wave"}:
        return ".wav"
    # MP3 형식 확인 (가장 일반적인 압축 오디오)
    if normalized_mime == "audio/mpeg":
        return ".mp3"
    # M4A/MP4 형식 확인 (AAC 코덱 기반 오디오)
    if normalized_mime in {"audio/mp4", "audio/x-m4a"}:
        return ".m4a"
    # 3단계: 인식할 수 없는 형식은 바이너리 확장자로 폴백
    return ".bin"


def _extract_transcript(payload: dict[str, Any]) -> str | None:
    """Azure Speech 실시간 REST 응답에서 최적의 전사 텍스트를 추출합니다.

    ``DisplayText``, ``NBest[].Display``, ``RecognizedPhrases`` 형식을 처리합니다.

    Args:
        payload: Azure Speech REST API의 JSON 응답 딕셔너리.

    Returns:
        발견된 최적의 전사 문자열, 또는 인식된 텍스트가 없는 경우 ``None``.
    """

    # 폴백 전략 1: DisplayText 필드에서 직접 추출 (가장 간단한 응답 형식)
    display_text = payload.get("DisplayText")
    if isinstance(display_text, str) and display_text.strip():
        return display_text.strip()

    # 폴백 전략 2: NBest 배열에서 최고 신뢰도 후보의 텍스트 추출
    nbest = payload.get("NBest")
    if isinstance(nbest, list):
        for candidate in nbest:
            if not isinstance(candidate, dict):
                continue
            # Display → Lexical → ITN → MaskedITN 순으로 우선순위 탐색
            for key in ("Display", "Lexical", "ITN", "MaskedITN"):
                value = candidate.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

    # 폴백 전략 3: RecognizedPhrases 배열에서 구간별 텍스트 추출 (배치 API 호환)
    recognized_phrases = payload.get("RecognizedPhrases")
    if isinstance(recognized_phrases, list):
        for phrase in recognized_phrases:
            if not isinstance(phrase, dict):
                continue
            # 구간의 Display 필드 직접 확인
            display = phrase.get("Display")
            if isinstance(display, str) and display.strip():
                return display.strip()
            # 구간 내 NBest 배열에서 후보 텍스트 추출
            nbest = phrase.get("NBest")
            if isinstance(nbest, list):
                for candidate in nbest:
                    if not isinstance(candidate, dict):
                        continue
                    display = candidate.get("Display")
                    if isinstance(display, str) and display.strip():
                        return display.strip()

    # 모든 폴백 전략 실패 시 None 반환
    return None



# --- 전사기 클래스 -----------------------------------------------------------

class AzureSpeechTranscriber:
    """Azure Speech REST v1 API를 사용하여 음성 오디오를 텍스트로 변환합니다.

    이전 버전에서는 배치 전사 API (v3.2)를 사용하여 폴링이 필요했으나,
    REST v1 API는 WAV 바이트를 직접 POST하면 즉시 전사 결과를 반환합니다.
    이로 인해 지연 시간이 10-30초에서 1-3초로 크게 단축됩니다.

    Attributes:
        _settings: Azure Speech 구성을 포함하는 애플리케이션 설정.
    """

    def __init__(self, settings: Settings) -> None:
        """애플리케이션 설정으로 전사기를 초기화합니다.

        Args:
            settings: Azure Speech 엔드포인트, 언어 구성을
                제공하는 애플리케이션 설정.
        """
        self._settings = settings

    def _require_endpoint(self) -> str:
        """Azure Speech Cognitive Services 기본 URL을 반환합니다.

        ``AZURE_SPEECH_ENDPOINT``는 Azure Cognitive Services 엔드포인트 URL로
        설정해야 합니다. 토큰 발급 (/sts/v1.0/issuetoken) 및 배치 API에 사용됩니다.
        예: ``https://<resource>.cognitiveservices.azure.com/``

        주의: REST v1 음성 인식 경로는 이 엔드포인트에서 직접 지원되지 않습니다.
        대신 _get_regional_stt_url()로 리전 엔드포인트를 사용합니다.

        Returns:
            후행 슬래시가 제거된 엔드포인트 URL.

        Raises:
            RuntimeError: ``AZURE_SPEECH_ENDPOINT``가 구성되지 않은 경우.
        """

        endpoint: str | None = getattr(self._settings, "azure_speech_endpoint", None)
        if not endpoint:
            raise RuntimeError(
                "Azure Speech endpoint is not configured. Set AZURE_SPEECH_ENDPOINT in backend/.env."
            )
        return endpoint.rstrip("/")

    def _require_region(self) -> str:
        """Azure Speech 리전을 반환하거나 명확한 오류를 발생시킵니다.

        ``AZURE_SPEECH_REGION``은 Azure Speech 리소스가 배포된 리전 코드입니다.
        리전 엔드포인트 URL (``https://{region}.stt.speech.microsoft.com``)
        구성에 사용됩니다.

        Returns:
            리전 코드 문자열 (예: ``"eastus2"``).

        Raises:
            RuntimeError: ``AZURE_SPEECH_REGION``이 구성되지 않은 경우.
        """

        region: str | None = getattr(self._settings, "azure_speech_region", None)
        if not region:
            raise RuntimeError(
                "Azure Speech region is not configured. Set AZURE_SPEECH_REGION in backend/.env."
            )
        return region.strip()

    def _get_regional_stt_url(self, language: str) -> str:
        """리전 기반 REST v1 음성 인식 전체 URL을 반환합니다.

        Azure AI Services (kind=AIServices) 리소스는 REST v1 경로를
        리소스 엔드포인트에서 직접 지원하지 않으므로,
        리전 엔드포인트를 사용해야 합니다.

        Args:
            language: BCP-47 로케일 코드 (예: ``"ko-KR"``).

        Returns:
            완전한 REST v1 요청 URL.
        """

        # 리전 코드를 사용하여 STT 리전 엔드포인트 기본 URL 구성
        region = self._require_region()
        # 전체 URL: https://{리전}.stt.speech.microsoft.com + REST v1 경로 + 쿼리 파라미터
        return (
            f"https://{region}.stt.speech.microsoft.com"  # 리전별 음성 인식 호스트
            f"{_STT_REST_PATH}?language={language}&format=detailed"  # 언어 및 상세 응답 형식 지정
        )

    async def _get_bearer_token(self) -> str:
        """DefaultAzureCredential을 통해 단기 Entra ID 토큰을 획득합니다.

        ``AZURE_CLIENT_ID`` / ``AZURE_TENANT_ID`` / ``AZURE_CLIENT_SECRET``
        (또는 Azure SDK에서 지원하는 다른 자격 증명)을 자동으로 사용합니다.

        Returns:
            Azure Cognitive Services용 Entra ID 토큰 문자열.
        """

        async with DefaultAzureCredential() as credential:
            token = await credential.get_token("https://cognitiveservices.azure.com/.default")
        return str(token.token)

    async def _get_speech_token(self) -> str:
        """음성 서비스 전용 토큰을 발급받습니다.

        Azure AI Services (kind=AIServices) 리소스에서는 REST v1 경로가
        리소스 엔드포인트에서 직접 지원되지 않으므로,
        /sts/v1.0/issuetoken 엔드포인트를 통해 음성 전용 토큰을 발급받고
        리전 엔드포인트에서 사용합니다.

        Returns:
            음성 서비스 전용 Bearer 토큰 문자열.

        Raises:
            RuntimeError: 토큰 발급에 실패한 경우.
        """

        base_url = self._require_endpoint()
        entra_token = await self._get_bearer_token()

        token_url = f"{base_url}/sts/v1.0/issuetoken"
        token_timeout = aiohttp.ClientTimeout(total=10)

        async with aiohttp.ClientSession(timeout=token_timeout) as sess:
            async with sess.post(
                token_url,
                headers={"Authorization": f"Bearer {entra_token}"},
                data=b"",
            ) as r:
                if r.status != 200:
                    error_text = await r.text()
                    logger.error(
                        "_get_speech_token() failed: status=%d, body=%s",
                        r.status,
                        error_text[:200],
                    )
                    raise RuntimeError(
                        f"음성 토큰 발급 실패 (status {r.status}): {error_text[:200]}"
                    )
                speech_token = await r.text()

        logger.info(
            "_get_speech_token() speech token acquired: length=%d",
            len(speech_token),
        )
        return speech_token

    async def transcribe_audio_bytes(
        self,
        audio_bytes: bytes,
        *,
        mime_type: str,
        file_name: str | None = None,
        language: str | None = None,
    ) -> str:
        """오디오를 WAV로 변환하고 Azure Speech REST v1 API를 통해 즉시 전사합니다.

        이전 배치 API (v3.2) 대신 REST v1 API를 사용하여 폴링 없이
        즉시 전사 결과를 받습니다. 짧은 음성 메시지에 최적화되어 있습니다.

        Args:
            audio_bytes: 원시 오디오 바이트 (OGG, MP3, WAV, WebM 등).
            mime_type: 형식 감지를 위한 오디오의 MIME 타입.
            file_name: 확장자 폴백을 위한 선택적 원본 파일명.
            language: BCP-47 언어 코드 (예: ``"ko-KR"``). 구성된
                기본 언어로 폴백합니다.

        Returns:
            전사된 텍스트 문자열.

        Raises:
            RuntimeError: 오디오가 비어 있거나, 너무 크거나, 변환에 실패하거나,
                전사가 실패한 경우.
        """

        # 1단계: 입력 오디오 로깅 및 유효성 검증
        logger.info(
            "transcribe_audio_bytes() started: audio_size=%d, mime_type=%s, file_name=%s, language=%s",
            len(audio_bytes),
            mime_type,
            file_name,
            language,
        )
        # 빈 오디오 파일 검증
        if not audio_bytes:
            raise RuntimeError("Audio file is empty.")
        # 오디오 크기 상한 검증 (MAX_AUDIO_BYTES 초과 방지)
        if len(audio_bytes) > MAX_AUDIO_BYTES:
            raise RuntimeError("Audio file is too large to transcribe.")

        # 2단계: 원본 오디오를 16kHz 모노 PCM WAV로 변환 (별도 스레드에서 실행)
        wav_bytes = await asyncio.to_thread(
            self._convert_audio_bytes_to_wav,
            audio_bytes,
            mime_type,
            file_name,
        )
        logger.info("transcribe_audio_bytes() WAV conversion complete: wav_size=%d", len(wav_bytes))
        # 3단계: WAV 바이트를 Azure Speech REST v1 API로 전송하여 전사 수행
        return await self._transcribe_wav_rest(
            wav_bytes,
            language=language or self._settings.azure_speech_language,  # 언어 미지정 시 설정 기본값 사용
        )

    def decode_base64_audio(self, audio_base64: str) -> bytes:
        """API 요청에서 base64 오디오 페이로드를 디코딩합니다.

        Args:
            audio_base64: 프론트엔드에서 전달된 Base64로 인코딩된 오디오 문자열.

        Returns:
            디코딩된 원시 오디오 바이트.

        Raises:
            RuntimeError: 페이로드가 유효한 base64가 아닌 경우.
        """

        logger.debug("decode_base64_audio() decoding base64 audio: input_length=%d", len(audio_base64))
        try:
            decoded = base64.b64decode(audio_base64, validate=True)
            logger.info("decode_base64_audio() decoded successfully: decoded_size=%d", len(decoded))
            return decoded
        except (ValueError, TypeError) as error:
            logger.warning("decode_base64_audio() invalid base64: %s", error)
            raise RuntimeError("Audio payload is not valid base64.") from error

    def _convert_audio_bytes_to_wav(self, audio_bytes: bytes, mime_type: str, file_name: str | None) -> bytes:
        """임의의 텔레그램 오디오를 16 kHz 모노 PCM WAV로 변환합니다.

        Args:
            audio_bytes: ffmpeg가 지원하는 모든 형식의 원시 오디오 바이트.
            mime_type: 형식 감지를 위한 MIME 타입.
            file_name: 확장자 폴백을 위한 선택적 파일명.

        Returns:
            16 kHz 모노 PCM WAV 오디오 바이트.

        Raises:
            RuntimeError: ffmpeg 변환이 실패한 경우.
        """

        import imageio_ffmpeg

        # 입력 오디오의 파일 확장자 결정
        extension = _resolve_audio_extension(mime_type, file_name)
        logger.info(
            "_convert_audio_bytes_to_wav() starting: input_size=%d, mime_type=%s, extension=%s",
            len(audio_bytes),
            mime_type,
            extension,
        )
        # 임시 디렉토리에서 입출력 파일 경로 생성
        with TemporaryDirectory(prefix="telegram-voice-") as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / f"input{extension}"  # 원본 오디오 파일 경로
            output_path = temp_path / "output.wav"  # 변환된 WAV 파일 경로
            input_path.write_bytes(audio_bytes)  # 원본 오디오 바이트를 파일로 저장

            # ffmpeg 명령 구성 및 실행
            result = subprocess.run(
                [
                    imageio_ffmpeg.get_ffmpeg_exe(),  # ffmpeg 실행 파일 경로
                    "-y",               # 출력 파일 덮어쓰기 허용
                    "-i",               # 입력 파일 지정
                    str(input_path),
                    "-vn",              # 비디오 스트림 제거 (오디오만 추출)
                    "-acodec",          # 오디오 코덱 지정
                    "pcm_s16le",        # 16비트 리틀엔디안 PCM (WAV 표준)
                    "-ac",              # 오디오 채널 수 지정
                    "1",                # 모노 채널 (음성 인식에 최적)
                    "-ar",              # 오디오 샘플링 레이트 지정
                    "16000",            # 16kHz (Azure Speech 권장 사양)
                    str(output_path),
                ],
                check=False,           # 비정상 종료 시 예외 발생하지 않음
                capture_output=True,   # stdout/stderr 캡처
                text=True,             # 출력을 문자열로 디코딩
            )
            # ffmpeg 실행 결과 검증
            if result.returncode != 0 or not output_path.exists():
                stderr_excerpt = (
                    result.stderr or "Audio conversion failed: ffmpeg returned a non-zero exit code"
                ).strip()[-500:]  # 에러 메시지 마지막 500자만 추출
                logger.error(
                    "_convert_audio_bytes_to_wav() ffmpeg failed: returncode=%d, stderr=%s",
                    result.returncode,
                    stderr_excerpt,
                )
                raise RuntimeError(f"Failed to convert Telegram voice message to WAV. {stderr_excerpt}")

            wav_data = output_path.read_bytes()  # 변환된 WAV 파일을 바이트로 읽기
            logger.info("_convert_audio_bytes_to_wav() completed: output_size=%d", len(wav_data))
            return wav_data

    async def _transcribe_wav_rest(self, wav_bytes: bytes, *, language: str) -> str:
        """Azure Speech REST v1 API로 WAV 바이트를 직접 전사합니다.

        리전 엔드포인트 (https://{region}.stt.speech.microsoft.com)를 사용하며,
        /sts/v1.0/issuetoken으로 발급받은 음성 전용 토큰으로 인증합니다.

        Azure AI Services (kind=AIServices) 리소스에서는 REST v1 경로가
        리소스 엔드포인트에서 직접 지원되지 않으므로 리전 엔드포인트를 사용합니다.

        Args:
            wav_bytes: 전사할 16kHz 모노 PCM WAV 오디오 바이트.
            language: BCP-47 로케일 코드 (예: ``"ko-KR"``).

        Returns:
            전사된 텍스트 문자열.

        Raises:
            RuntimeError: API 호출 또는 결과 추출이 실패한 경우.
        """

        # 리전 기반 REST v1 URL 구성
        stt_url = self._get_regional_stt_url(language)

        logger.info(
            "_transcribe_wav_rest() REST v1 transcription starting: wav_size=%d, language=%s, url=%s",
            len(wav_bytes),
            language,
            stt_url.split("?")[0],  # 쿼리 파라미터 제외한 base URL만 로깅
        )

        # 음성 전용 토큰 발급 (Entra ID → /sts/v1.0/issuetoken)
        speech_token = await self._get_speech_token()
        headers = {
            "Authorization": f"Bearer {speech_token}",
            # WAV PCM 16kHz 모노 형식 명시
            "Content-Type": "audio/wav; codecs=audio/pcm; samplerate=16000",
            "Accept": "application/json",
        }
        # REST v1은 즉시 응답하므로 짧은 타임아웃 사용
        rest_timeout = aiohttp.ClientTimeout(total=30)

        async with aiohttp.ClientSession(timeout=rest_timeout) as sess:
            async with sess.post(stt_url, headers=headers, data=wav_bytes) as r:
                if r.status != 200:
                    error_text = await r.text()
                    logger.error(
                        "_transcribe_wav_rest() REST v1 failed: status=%d, body=%s",
                        r.status,
                        error_text[:300],
                    )
                    raise RuntimeError(
                        f"Azure Speech REST v1 recognition failed with status {r.status}. "
                        f"{error_text[:200]}"
                    )

                payload = await r.json()
                logger.info(
                    "_transcribe_wav_rest() REST v1 response: status=%s",
                    payload.get("RecognitionStatus"),
                )

        # RecognitionStatus 확인
        recognition_status = payload.get("RecognitionStatus", "")
        if recognition_status == "NoMatch":
            raise RuntimeError("음성이 인식되지 않았습니다. 다시 시도해주세요.")
        if recognition_status not in ("Success", ""):
            raise RuntimeError(
                f"Azure Speech 인식 실패: {recognition_status}"
            )

        # _extract_transcript는 DisplayText, NBest 형식을 모두 처리합니다
        transcript = _extract_transcript(payload)
        if not transcript:
            raise RuntimeError("Azure Speech REST v1 전사 결과가 비어 있습니다.")

        logger.info(
            "_transcribe_wav_rest() completed: transcript_length=%d, text=%s",
            len(transcript),
            transcript[:100],
        )
        return transcript
