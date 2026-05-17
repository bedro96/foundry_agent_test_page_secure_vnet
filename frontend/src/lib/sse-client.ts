/**
 * 채팅 엔드포인트를 위한 클라이언트 측 SSE 스트리밍 클라이언트.
 *
 * 인증을 위해 클라이언트에 노출된 `NEXT_PUBLIC_BACKEND_API_KEY`를 사용하여
 * `NEXT_PUBLIC_BACKEND_URL`을 통해 백엔드에 연결합니다.
 * @module sse-client
 */
import { config } from "@/lib/config"; // 클라이언트 측 환경 구성
import type { ApiMessage, StreamChatEvent } from "@/lib/chat-types"; // 채팅 관련 타입 정의

/**
 * 원시 SSE 데이터 문자열을 타입이 지정된 {@link StreamChatEvent}로 정규화합니다.
 *
 * 먼저 JSON 파싱을 시도하고, 실패 시 원시 문자열을 데이터 페이로드로 처리합니다.
 *
 * @param eventType - `event:` 필드에서 파싱된 SSE 이벤트 타입.
 * @param rawData - 이 프레임의 연결된 `data:` 라인들.
 * @returns 정규화된 이벤트, 또는 데이터가 비어있으면 `null`.
 */
const normalizeEvent = (eventType: string, rawData: string): StreamChatEvent | null => {
  // 빈 데이터는 유효하지 않은 프레임으로 판단하여 null 반환
  if (!rawData.trim()) {
    return null;
  }

  try {
    // JSON 파싱 시도: 구조화된 페이로드에서 이벤트 정보 추출
    const payload = JSON.parse(rawData) as {
      event?: string;
      data?: unknown;
      conversation_id?: string | null;
    };

    return {
      event: eventType || payload.event || "message", // 이벤트 타입 우선순위 적용
      data: payload.data ?? payload, // data 필드가 없으면 전체 페이로드 사용
      conversation_id: payload.conversation_id,
    };
  } catch {
    // JSON 파싱 실패 시 원시 문자열을 메시지 데이터로 처리
    return {
      event: eventType || "message",
      data: rawData,
    };
  }
};

/**
 * 단일 SSE 프레임(이중 개행 사이의 텍스트)을 {@link StreamChatEvent}로 파싱합니다.
 *
 * SSE 사양에 따라 `event:` 및 `data:` 라인을 추출하고
 * JSON 역직렬화를 위해 {@link normalizeEvent}에 위임합니다.
 *
 * @param frame - 원시 SSE 프레임 문자열.
 * @returns 파싱된 이벤트, 또는 프레임에 데이터 라인이 없으면 `null`.
 */
const parseFrame = (frame: string): StreamChatEvent | null => {
  // 프레임을 줄 단위로 분리하고 빈 줄 제거
  const lines = frame
    .split(/\r?\n/)
    .filter((line) => line.length > 0);

  let eventType = "message"; // 기본 이벤트 타입
  const dataLines: string[] = []; // data: 라인 수집용 배열

  // 각 줄에서 event: 및 data: 접두사를 파싱
  for (const line of lines) {
    if (line.startsWith("event:")) {
      // event: 필드에서 이벤트 타입 추출
      eventType = line.slice(6).trim() || eventType;
      continue;
    }

    if (line.startsWith("data:")) {
      // data: 필드에서 페이로드 데이터 추출 (공백 처리 포함)
      dataLines.push(line.startsWith("data: ") ? line.slice(6) : line.slice(5));
    }
  }

  // 수집된 데이터 라인을 결합하여 정규화된 이벤트로 변환
  return normalizeEvent(eventType, dataLines.join("\n"));
};

/**
 * 백엔드 SSE 엔드포인트에서 채팅 대화를 스트리밍합니다.
 *
 * `/api/chat/stream`으로 `POST` 연결을 열고, 청크된 본문을 읽으며,
 * 파싱된 모든 SSE 프레임에 대해 `onEvent`를 호출합니다. 중단 신호를 자동으로
 * 처리하고 완료 시 리더를 정리합니다.
 *
 * @param messages - 백엔드 API 형식으로 포맷된 대화 기록.
 * @param conversationId - 다중 턴 연속성을 위한 기존 대화 ID, 또는 `null`.
 * @param onEvent - 파싱된 각 {@link StreamChatEvent}에 대해 호출되는 콜백.
 * @param signal - 스트림을 취소하기 위한 선택적 `AbortSignal`.
 * @throws {Error} 백엔드가 비정상 상태를 반환하거나 스트림이 예기치 않게 닫힐 때.
 */
export async function streamChat(
  messages: ApiMessage[],
  conversationId: string | null,
  onEvent: (event: StreamChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  console.log(`[sse-client] Opening SSE connection: messages=${messages.length} conversationId=${conversationId ?? "new"}`);

  // 요청 헤더 구성: SSE 수신용 Accept, JSON 콘텐츠 타입
  const headers: Record<string, string> = {
      Accept: "text/event-stream",
      "Content-Type": "application/json",
    };
    // 클라이언트 측 API 키가 설정되어 있으면 x-api-key 헤더 추가
    if (config.backendApiKey) {
      headers["x-api-key"] = config.backendApiKey;
    }

    // 백엔드 채팅 스트리밍 엔드포인트로 POST 요청 전송
    const response = await fetch(`${config.backendUrl}/api/chat/stream`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      messages,
      conversation_id: conversationId, // 다중 턴 대화를 위한 대화 ID
    }),
    signal, // 사용자 취소를 위한 AbortSignal 연결
  });

  // HTTP 응답 상태 검증: 서버 에러(5xx) 또는 클라이언트 에러 구분 처리
  if (!response.ok) {
    console.log(`[sse-client] SSE connection failed: status=${response.status}`);
    throw new Error(
      response.status >= 500
        ? "The backend is unavailable right now."
        : "The chat request could not be completed.",
    );
  }

  // 스트리밍 응답 본문 존재 여부 확인
  if (!response.body) {
    console.log("[sse-client] SSE response body is unavailable");
    throw new Error("Streaming response body is unavailable.");
  }

  console.log(`[sse-client] SSE connected: status=${response.status}`);
  let frameCount = 0; // 처리된 SSE 프레임 카운터
  const reader = response.body.getReader(); // ReadableStream 리더 획득
  const decoder = new TextDecoder(); // 바이너리를 UTF-8 문자열로 디코딩하는 디코더
  let buffer = ""; // 불완전한 프레임을 버퍼링하는 문자열

  try {
    // 메인 스트림 읽기 루프
    while (true) {
      const { done, value } = await reader.read();
      // 수신된 청크를 디코딩하여 버퍼에 추가
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

      // 이중 개행으로 완성된 SSE 프레임 분리; 마지막 불완전 프레임은 버퍼에 유지
      const frames = buffer.split(/\r?\n\r?\n/);
      buffer = frames.pop() || "";

      // 각 완성된 프레임을 파싱하고 콜백으로 전달
      for (const frame of frames) {
        const parsed = parseFrame(frame);
        if (parsed) {
          frameCount++;
          onEvent(parsed);
        }
      }

      // 스트림 종료 시 버퍼에 남은 마지막 프레임 처리
      if (done) {
        const finalFrame = parseFrame(buffer);
        if (finalFrame) {
          frameCount++;
          onEvent(finalFrame);
        }
        break;
      }
    }
    console.log(`[sse-client] SSE stream completed: frames=${frameCount}`);
  } catch (error) {
    // 사용자가 AbortSignal로 스트림을 취소한 경우 정상 종료 처리
    if (signal?.aborted || (error instanceof DOMException && error.name === "AbortError")) {
      console.log(`[sse-client] SSE stream aborted by user: frames=${frameCount}`);
      return;
    }

    // 예기치 않은 스트림 에러 발생 시 원인 포함하여 재전파
    console.log(`[sse-client] SSE stream error: frames=${frameCount} error=${error instanceof Error ? error.message : "unknown"}`);
    throw new Error(
      error instanceof Error
        ? error.message
        : "The chat stream closed unexpectedly.",
      { cause: error },
    );
  } finally {
    // 정리: 리더 잠금 해제 (리소스 누수 방지)
    reader.releaseLock();
    console.log(`[sse-client] SSE reader released: totalFrames=${frameCount}`);
  }
}
