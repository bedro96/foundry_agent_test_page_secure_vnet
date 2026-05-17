/**
 * 클라이언트 측 구성 상수.
 *
 * 이 값들은 `NEXT_PUBLIC_` 접두사 규칙을 통해 빌드 시
 * 클라이언트 측 JavaScript 번들에 포함됩니다.
 *
 * 환경 변수:
 * - `NEXT_PUBLIC_BACKEND_URL`     — 백엔드 API 기본 URL (기본값: `http://localhost:8000`).
 *                                    빌드 시 클라이언트 JS에 포함됨.
 * - `NEXT_PUBLIC_BACKEND_API_KEY` — 클라이언트 측 백엔드 호출을 위한 API 키.
 *                                    브라우저에서 `x-api-key` 헤더로 전송됨.
 * - `BACKEND_API_KEY`             — 서버 측 전용 백엔드 호출을 위한 API 키 (클라이언트에 노출되지 않음).
 * - `APP_URL`                     — 서버 측 헬퍼가 사용하는 프론트엔드 애플리케이션 URL.
 * @module config
 */

/** `NEXT_PUBLIC_*` 환경 변수에서 읽어온 클라이언트 측 런타임 구성. */
export const config = {
  /** 클라이언트 측 fetch 호출에서 사용하는 백엔드 API 기본 URL. 미설정 시 localhost로 폴백. */
  backendUrl: process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000",
  /** 클라이언트 측 요청에서 `x-api-key` 헤더로 첨부되는 API 키. 미설정 시 빈 문자열. */
  backendApiKey: process.env.NEXT_PUBLIC_BACKEND_API_KEY || "",
};
