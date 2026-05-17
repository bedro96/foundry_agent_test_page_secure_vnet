/**
 * 서버 측 백엔드 통신 레이어.
 *
 * 이 모듈의 모든 함수는 Next.js API 라우트(서버 측)에서만 실행되며
 * 인증을 위해 서버 전용 `BACKEND_API_KEY` 환경 변수를 사용합니다.
 *
 * 사용되는 환경 변수:
 * - `NEXT_PUBLIC_BACKEND_URL` — Python 백엔드의 기본 URL (기본값: `http://backend:8000`).
 * - `BACKEND_API_KEY` — `x-api-key` 헤더로 전송되는 서버 측 API 키 (브라우저에 노출되지 않음).
 * @module backend
 */

/** 멀티모달 채팅 메시지의 텍스트 콘텐츠 부분. */
export type TextContentPart = {
  /** 텍스트 부분임을 식별하는 판별자. */
  type: "input_text";
  /** 텍스트 내용. */
  text: string;
};

/** 멀티모달 채팅 메시지의 이미지 콘텐츠 부분. */
export type ImageContentPart = {
  /** 이미지 부분임을 식별하는 판별자. */
  type: "input_image";
  /** 이미지의 데이터 URI 또는 HTTPS URL. */
  image_url: string;
  /** 비전 모델을 위한 해상도 힌트. */
  detail?: "low" | "high" | "auto" | "original";
};

/** 채팅 메시지에서 지원되는 모든 콘텐츠 부분 타입의 유니온. */
export type ContentPart = TextContentPart | ImageContentPart;

/** 백엔드 `/api/chat/stream` 엔드포인트로 전송되는 단일 채팅 메시지. */
export type BackendChatMessage = {
  /** 이 메시지를 작성한 역할. */
  role: "system" | "user" | "assistant";
  /** 일반 텍스트 또는 멀티모달 콘텐츠 부분 배열. */
  content: string | ContentPart[];
};

/** 백엔드 스트리밍 채팅 엔드포인트의 요청 본문. */
export type BackendChatRequest = {
  /** 새로운 사용자 턴을 포함한 정렬된 대화 기록. */
  messages: BackendChatMessage[];
  /** 다중 턴 연속성을 위한 선택적 대화 ID. */
  conversation_id?: string;
  /** 에이전트에 전달되는 임의의 키-값 메타데이터. */
  metadata?: Record<string, string>;
};

/** 백엔드 스트리밍 채팅 엔드포인트에서 발생하는 단일 SSE 프레임. */
export type BackendStreamEvent = {
  /** 프론트엔드가 이 프레임을 렌더링하는 방식을 제어하는 이벤트 카테고리. */
  event: "status" | "message" | "error" | "done";
  /** 페이로드 문자열 (텍스트 델타, 상태 설명, 또는 JSON 블롭). */
  data: string;
  /** 다중 턴 추적을 위해 에코 백되는 대화 ID. */
  conversation_id?: string | null;
};

/** 백엔드 음성 전사 엔드포인트의 요청 본문. */
export type BackendTranscriptionRequest = {
  /** Base64로 인코딩된 오디오 데이터. */
  audio_base64: string;
  /** 오디오의 MIME 타입 (예: `audio/webm`, `audio/wav`). */
  mime_type: string;
  /** 로깅 목적의 선택적 원본 파일 이름. */
  file_name?: string;
  /** 선택적 BCP-47 언어 힌트 (예: `en-US`). */
  language?: string;
};

/** 백엔드 음성 전사 엔드포인트의 응답. */
export type BackendTranscriptionResponse = {
  /** 전사된 텍스트. */
  text: string;
  /** 감지되었거나 확인된 BCP-47 언어 코드. */
  language: string;
};

/**
 * 알 수 없는 값을 {@link BackendTranscriptionResponse}로 검증하는 타입 가드.
 *
 * @param value - 확인할 값 (일반적으로 파싱된 JSON 본문).
 * @returns `value`에 필수 `text` 및 `language` 문자열 필드가 있으면 `true`.
 */
function isBackendTranscriptionResponse(value: unknown): value is BackendTranscriptionResponse {
  // null이 아닌 객체이며 text와 language가 문자열 타입인지 검증
  return (
    value !== null &&
    typeof value === "object" &&
    "text" in value &&
    typeof value.text === "string" &&
    "language" in value &&
    typeof value.language === "string"
  );
}

/**
 * `NEXT_PUBLIC_BACKEND_URL`에서 백엔드 기본 URL을 확인하고,
 * Docker 내부 호스트명 `http://backend:8000`으로 폴백합니다.
 *
 * @returns 후행 슬래시가 없는 백엔드 기본 URL.
 */
function getBackendBaseUrl(): string {
  // 환경 변수에서 백엔드 URL을 읽고, 없으면 Docker 내부 호스트명으로 폴백
  return process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://backend:8000";
}

/**
 * 서버-백엔드 호출을 위한 표준 요청 헤더를 구성합니다.
 *
 * `Content-Type: application/json`을 포함하며, 사용 가능한 경우
 * `BACKEND_API_KEY` 환경 변수의 `x-api-key` 헤더를 추가합니다.
 *
 * @returns `fetch`에 적합한 헤더 레코드.
 */
function buildBackendHeaders(): Record<string, string> {
  // 기본 JSON 콘텐츠 타입 헤더 설정
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };

  // 서버 전용 API 키를 환경 변수에서 읽어 x-api-key 헤더에 추가
  const apiKey = process.env.BACKEND_API_KEY;
  if (apiKey) {
    headers["x-api-key"] = apiKey;
  } else {
    console.warn("[backend] BACKEND_API_KEY is not set; requests will be sent without an API key header");
  }

  return headers;
}

/**
 * 백엔드 채팅 엔드포인트에 SSE 연결을 열고 파싱된 이벤트를 생성합니다.
 *
 * 제너레이터는 청크된 응답 본문을 읽고, 이중 개행 경계로 분할하며,
 * 각 파싱된 {@link BackendStreamEvent}를 생성합니다. 스트림은
 * `done` 이벤트가 수신되거나 본문이 끝나면 자동으로 종료됩니다.
 *
 * @param payload - 메시지 기록과 선택적 대화 ID를 포함한 채팅 요청.
 * @yields {BackendStreamEvent} 백엔드에서 파싱된 SSE 프레임.
 * @throws {Error} HTTP 응답 상태가 2xx가 아니거나 본문이 없을 때.
 */
export async function* streamBackendChat(
  payload: BackendChatRequest,
): AsyncGenerator<BackendStreamEvent, void, undefined> {
  // 백엔드 채팅 스트리밍 엔드포인트 URL 구성
  const url = `${getBackendBaseUrl()}/api/chat/stream`;
  console.info(`[backend] POST ${url}`);

  // SSE 스트리밍을 위한 POST 요청 전송 (캐시 비활성화)
  const response = await fetch(url, {
    method: "POST",
    headers: buildBackendHeaders(),
    body: JSON.stringify(payload),
    cache: "no-store",
  });

  // 응답 상태 확인: 비정상 상태 또는 본문 없음 시 에러 발생
  if (!response.ok || !response.body) {
    console.info(`[backend] POST ${url} failed: status=${response.status}`);
    throw new Error(`Backend request failed with status ${response.status}`);
  }

  console.info(`[backend] POST ${url} connected: status=${response.status}, streaming SSE`);
  let eventCount = 0; // 수신된 SSE 이벤트 카운터

  const decoder = new TextDecoder(); // 바이너리 청크를 UTF-8 문자열로 디코딩
  const reader = response.body.getReader(); // ReadableStream 리더 획득
  let buffer = ""; // 불완전한 SSE 프레임을 버퍼링하는 문자열
  let readerClosed = false; // 리더 중복 취소 방지 플래그

  /** 스트림 리더를 안전하게 취소하는 내부 헬퍼. 중복 호출을 방지합니다. */
  const cancelReader = async (): Promise<void> => {
    if (readerClosed) {
      return;
    }
    readerClosed = true;

    try {
      await reader.cancel();
    } catch (_error) {
      // 정리 실패 무시 — 호출자가 이미 스트림 결과를 처리 중.
    }
  };

  /** 리더 잠금을 안전하게 해제하는 내부 헬퍼. 이미 닫힌 경우 에러를 무시합니다. */
  const releaseReaderLock = (): void => {
    try {
      reader.releaseLock();
    } catch (_error) {
      // 스트림이 이미 닫힌 경우 해제 실패 무시.
    }
  };

  /**
   * 단일 SSE 블록(이중 개행으로 구분된 텍스트)을 파싱하여 이벤트 객체로 변환합니다.
   * @param block - 원시 SSE 블록 문자열
   * @returns 파싱된 이벤트 또는 데이터가 없으면 null
   */
  const parseBlock = (block: string): BackendStreamEvent | null => {
    let eventName = "message"; // 기본 이벤트 타입
    const dataLines: string[] = []; // data: 라인 수집 배열

    // 각 라인을 순회하며 event: 및 data: 접두사 추출
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) {
        eventName = line.slice(6).trim();
      }
      if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trim());
      }
    }

    // 데이터 라인이 없으면 유효하지 않은 프레임으로 판단
    if (dataLines.length === 0) {
      return null;
    }

    // 수집된 데이터 라인을 결합하여 JSON 파싱 후 이벤트 객체 구성
    const parsed = JSON.parse(dataLines.join("\n")) as Partial<BackendStreamEvent>;
    return {
      event: (parsed.event ?? eventName) as BackendStreamEvent["event"],
      data: typeof parsed.data === "string" ? parsed.data : "",
      conversation_id: parsed.conversation_id ?? null,
    };
  };

  try {
    // 메인 스트림 읽기 루프: 청크를 읽고 SSE 프레임으로 분할
    while (true) {
      const { done, value } = await reader.read();

      // 수신된 청크를 UTF-8로 디코딩하여 버퍼에 추가
      if (value) {
        buffer += decoder.decode(value, { stream: !done });
      } else if (done) {
        buffer += decoder.decode(); // 최종 디코더 플러시
      }

      // 이중 개행(\n\n)으로 완성된 SSE 블록 분리; 마지막 불완전 블록은 버퍼에 유지
      const blocks = buffer.split("\n\n");
      buffer = blocks.pop() ?? "";

      // 완성된 각 블록을 파싱하고 이벤트로 생성(yield)
      for (const block of blocks) {
        const event = parseBlock(block);
        if (event) {
          eventCount++;
          console.info(`[backend] SSE event #${eventCount}: type=${event.event}`);
          yield event;
          // "done" 이벤트 수신 시 스트림 종료
          if (event.event === "done") {
            console.info(`[backend] SSE stream done after ${eventCount} events`);
            return;
          }
        }
      }

      // 리더가 완료되면 루프 탈출
      if (done) {
        break;
      }
    }

    // 버퍼에 남아있는 마지막 불완전 블록 처리 시도
    if (buffer.trim()) {
      const event = parseBlock(buffer);
      if (event) {
        yield event;
      }
    }
  } finally {
    // 정리: 스트림 리더 취소 및 잠금 해제
    console.info(`[backend] SSE stream closed after ${eventCount} events`);
    await cancelReader();
    releaseReaderLock();
  }
}

/**
 * Base64로 인코딩된 오디오를 백엔드 전사 엔드포인트로 전송하고 결과를 반환합니다.
 *
 * @param payload - 오디오 데이터와 MIME 타입을 포함한 전사 요청.
 * @returns 전사된 텍스트와 감지된 언어.
 * @throws {Error} 백엔드가 비정상 상태, 잘못된 응답 형태, 또는 빈 텍스트를 반환할 때.
 */
export async function transcribeBackendAudio(
  payload: BackendTranscriptionRequest,
): Promise<BackendTranscriptionResponse> {
  // 백엔드 음성 전사 엔드포인트 URL 구성
  const url = `${getBackendBaseUrl()}/api/speech/transcribe`;
  console.info(`[backend] POST ${url}`);

  // Base64 오디오 데이터를 백엔드 전사 API로 전송
  const response = await fetch(url, {
    method: "POST",
    headers: buildBackendHeaders(),
    body: JSON.stringify(payload),
    cache: "no-store",
  });

  console.info(`[backend] POST ${url} response: status=${response.status}`);

  // 응답 본문을 JSON으로 파싱 시도; 실패 시 null 처리
  let parsedBody: unknown = null;
  try {
    parsedBody = await response.json();
  } catch {
    parsedBody = null;
  }

  // 비정상 HTTP 상태 시 백엔드의 상세 에러 메시지를 추출하여 예외 발생
  if (!response.ok) {
    const detail =
      parsedBody && typeof parsedBody === "object" && "detail" in parsedBody && typeof parsedBody.detail === "string"
        ? parsedBody.detail
        : `Backend transcription request failed with status ${response.status}`;
    throw new Error(detail);
  }

  // 응답 형태가 예상된 전사 응답 구조인지 타입 가드로 검증
  if (!isBackendTranscriptionResponse(parsedBody)) {
    throw new Error("Backend transcription returned an invalid response.");
  }

  // 전사 결과가 빈 텍스트인 경우 에러 처리
  if (!parsedBody.text.trim()) {
    throw new Error("Backend transcription returned empty text.");
  }

  return parsedBody as BackendTranscriptionResponse;
}