/**
 * 채팅 기능을 위한 공유 TypeScript 타입.
 *
 * 이 타입들은 채팅 데이터 모델의 일관성을 유지하기 위해
 * 클라이언트 측 컴포넌트와 서버 측 라우트 핸들러 모두에서 사용됩니다.
 * @module chat-types
 */

/** 메시지 버블을 렌더링하는 데 사용되는 시각적 역할. user/assistant는 대화 참여자, status/error는 시스템 알림. */
export type ChatRole = "user" | "assistant" | "status" | "error";

/**
 * 멀티모달 API 메시지 내부의 단일 콘텐츠 부분.
 *
 * 텍스트 세그먼트 또는 인라인 이미지 참조를 나타내는 판별 유니온 타입.
 */
export type ApiContentPart =
  | { type: "input_text"; text: string }       // 텍스트 콘텐츠 부분
  | { type: "input_image"; image_url: string; detail?: string }; // 이미지 콘텐츠 부분

/** 백엔드 `/api/chat/stream` 엔드포인트가 기대하는 형식의 메시지. */
export interface ApiMessage {
  /** 이 메시지를 작성한 역할. */
  role: "user" | "assistant";
  /** 일반 텍스트 또는 멀티모달 콘텐츠 부분 배열. */
  content: string | ApiContentPart[];
}

/** 스트리밍 중 어시스턴트가 제공하는 인용 출처. */
export interface SourceCitation {
  /** 사람이 읽을 수 있는 제목 또는 URL로 대체. */
  title: string;
  /** 인용된 리소스의 정규 URL. */
  url: string;
  /** 선택적 짧은 레이블 (예: "web", "document"). */
  label?: string;
}

/** 채팅 응답과 함께 반환되는 토큰 사용량 및 성능 메트릭. */
export interface UsageMetrics {
  /** 프롬프트의 토큰 수. */
  promptTokens?: number;
  /** 완성에서 생성된 토큰 수. */
  completionTokens?: number;
  /** 총 토큰 수 (프롬프트 + 완성). */
  totalTokens?: number;
  /** 엔드투엔드 응답 시간(밀리초). */
  responseTimeMs?: number;
  /** 이 응답에 사용된 모델 식별자. */
  model?: string;
}

/** 프론트엔드 상태에서 표현되는 채팅 메시지. */
export interface ChatMessage {
  /** 고유 메시지 식별자 (UUID 또는 타임스탬프 기반). */
  id: string;
  /** 메시지 버블 렌더링 방식을 제어하는 시각적 역할. */
  role: ChatRole;
  /** 메시지의 일반 텍스트 내용. */
  content: string;
  /** 선택적 멀티모달 콘텐츠 부분 (이미지 + 텍스트). */
  contentParts?: ApiContentPart[];
  /** 스트리밍 중 제공된 인용. */
  sources?: SourceCitation[];
}

/** 스트리밍 채팅 엔드포인트에서 수신한 단일 파싱된 SSE 이벤트. */
export interface StreamChatEvent {
  /** 이벤트 타입 문자열 (예: `"message"`, `"status"`, `"done"`). */
  event: string;
  /** 파싱된 페이로드 — 이벤트 타입에 따라 형태가 달라짐. */
  data: unknown;
  /** 다중 턴 연속성을 위한 대화 ID. */
  conversation_id?: string | null;
}
