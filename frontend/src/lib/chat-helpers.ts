/**
 * 스트리밍 이벤트에서 구조화된 데이터를 추출하기 위한 채팅 헬퍼 유틸리티.
 *
 * 이 순수 함수들은 느슨한 타입의 SSE 페이로드를 채팅 UI가 렌더링할 수 있는
 * 강타입의 상태 텍스트, 출처 인용, 사용량 메트릭으로 파싱합니다.
 * @module chat-helpers
 */
import type { SourceCitation, UsageMetrics } from "@/lib/chat-types"; // 출처 인용 및 사용량 메트릭 타입

/**
 * 알 수 없는 값을 일반 객체 레코드로 안전하게 캐스팅합니다.
 *
 * @param value - 확인할 값.
 * @returns `Record<string, unknown>`으로 캐스팅된 값, 또는 객체가 아닌 경우 `null`.
 */
const asRecord = (value: unknown): Record<string, unknown> | null =>
  // null이 아닌 객체이며 배열이 아닌 경우에만 레코드로 캐스팅
  typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;

/**
 * 알 수 없는 값을 유한한 숫자로 변환합니다.
 *
 * 숫자와 문자열 입력을 모두 처리합니다. 숫자가 아니거나
 * 유한하지 않은 값에 대해 `undefined`를 반환합니다.
 *
 * @param value - 변환할 값.
 * @returns 유한한 숫자, 또는 `undefined`.
 */
const asNumber = (value: unknown): number | undefined => {
  // 유한한 숫자 타입인 경우 그대로 반환
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }

  // 문자열인 경우 숫자로 변환 후 유한성 검증
  if (typeof value === "string") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : undefined;
  }

  // 그 외 타입은 변환 불가
  return undefined;
};

/**
 * 느슨한 타입의 SSE 페이로드에서 후보 레코드 객체를 수집합니다.
 *
 * 일반적인 중첩 키(`data`, `metrics`, `usage`, `token_usage`,
 * `metadata`)를 검색하여 다운스트림 추출기가 균일하게 스캔할 수 있도록 합니다.
 *
 * @param value - 원시 SSE 이벤트 데이터.
 * @returns 페이로드에서 발견된 null이 아닌 레코드 객체 배열.
 */
const candidateRecords = (value: unknown): Record<string, unknown>[] => {
  // 최상위 값을 레코드로 변환 시도
  const record = asRecord(value);
  if (!record) {
    return [];
  }

  // 최상위 레코드와 일반적인 중첩 키들을 후보 목록으로 수집
  return [
    record,
    asRecord(record.data),       // data 하위 객체
    asRecord(record.metrics),    // metrics 하위 객체
    asRecord(record.usage),      // usage 하위 객체
    asRecord(record.token_usage), // token_usage 하위 객체
    asRecord(record.metadata),   // metadata 하위 객체
  ].filter((candidate): candidate is Record<string, unknown> => Boolean(candidate));
};

/**
 * 후보 키 중에서 처음 발견된 비어있지 않은 문자열 값을 반환합니다.
 *
 * @param record - 검색할 객체.
 * @param keys - 확인할 속성 이름의 정렬된 목록.
 * @returns 트리밍된 문자열 값, 또는 일치하는 것이 없으면 `undefined`.
 */
const firstString = (
  record: Record<string, unknown>,
  keys: string[],
): string | undefined => {
  // 키 목록을 순서대로 순회하며 첫 번째 유효한 문자열 값 반환
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }

  return undefined;
};

/**
 * 문자열이 안전한 HTTP(S) URL처럼 보이는지 확인합니다.
 *
 * @param value - 테스트할 문자열.
 * @returns 값이 `http://` 또는 `https://`로 시작하면 `true`.
 */
const isSafeUrl = (value: string): boolean => /^https?:\/\//i.test(value);

/**
 * 느슨한 타입의 SSE 페이로드에서 사람이 읽을 수 있는 상태 메시지를 추출합니다.
 *
 * 페이로드와 중첩 후보에서 일반적인 텍스트 키(`message`, `status`, `text` 등)를
 * 검색합니다. 배열은 ` · `로 결합됩니다.
 *
 * @param value - 원시 이벤트 데이터 (문자열, 배열, 또는 객체).
 * @returns 추출된 상태 텍스트, 또는 의미 있는 것을 찾지 못한 경우 `null`.
 */
export const extractStatusText = (value: unknown): string | null => {
  // 문자열 값은 트리밍 후 직접 반환
  if (typeof value === "string") {
    return value.trim() || null;
  }

  // 배열인 경우 각 항목에서 상태 텍스트를 재귀적으로 추출하여 결합
  if (Array.isArray(value)) {
    const text = value
      .map((entry) => extractStatusText(entry))
      .filter((entry): entry is string => Boolean(entry))
      .join(" · "); // 구분자로 결합

    return text || null;
  }

  // 후보 레코드에서 일반적인 텍스트 키를 순서대로 검색
  for (const record of candidateRecords(value)) {
    const text = firstString(record, [
      "message",     // 메시지
      "status",      // 상태
      "text",        // 텍스트
      "detail",      // 상세 정보
      "summary",     // 요약
      "phase",       // 단계
      "tool",        // 도구
      "description", // 설명
    ]);

    if (text) {
      return text;
    }
  }

  return null;
};

/**
 * 단일 원시 값을 가능한 경우 {@link SourceCitation}으로 정규화합니다.
 *
 * @param value - 문자열 URL 또는 URL/제목 필드가 있는 객체.
 * @returns 정규화된 인용, 또는 값이 유효한 출처가 아닌 경우 `null`.
 */
const normalizeSource = (value: unknown): SourceCitation | null => {
  // 문자열 URL인 경우 http로 시작하는지 확인 후 인용 생성
  if (typeof value === "string") {
    return value.startsWith("http")
      ? { title: value, url: value }
      : null;
  }

  // 객체를 레코드로 변환 시도
  const record = asRecord(value);
  if (!record) {
    return null;
  }

  // URL 관련 키에서 URL 추출 및 안전성 검증
  const url = firstString(record, ["url", "href", "link"]);
  if (!url || !isSafeUrl(url)) {
    return null;
  }

  // 제목, 레이블, URL로 정규화된 인용 객체 생성
  return {
    title: firstString(record, ["title", "label", "name", "text"]) || url,
    label: firstString(record, ["label", "type", "source"]),
    url,
  };
};

/**
 * 느슨한 타입의 SSE 페이로드에서 모든 고유 출처 인용을 추출합니다.
 *
 * 중첩 키(`sources`, `citations`, `references`, `links`)를 검색하고
 * URL로 중복을 제거합니다.
 *
 * @param value - 원시 이벤트 데이터.
 * @returns 고유한 {@link SourceCitation} 객체 배열.
 */
export const extractSources = (value: unknown): SourceCitation[] => {
  // URL 기준 중복 제거를 위한 Map
  const sources = new Map<string, SourceCitation>();
  // 후보 레코드에서 출처 관련 중첩 키 수집
  const records = candidateRecords(value);
  const lists = [
    value,
    ...records.flatMap((record) => [
      record.sources,     // sources 배열
      record.citations,   // citations 배열
      record.references,  // references 배열
      record.links,       // links 배열
    ]),
  ];

  // 각 리스트를 순회하며 유효한 인용을 Map에 추가 (URL 기준 중복 제거)
  for (const list of lists) {
    if (!Array.isArray(list)) {
      continue;
    }

    for (const item of list) {
      const source = normalizeSource(item);
      if (source) {
        sources.set(source.url, source);
      }
    }
  }

  return [...sources.values()];
};

/**
 * 느슨한 타입의 SSE 페이로드에서 토큰 사용량 및 성능 메트릭을 추출합니다.
 *
 * `prompt_tokens`, `completion_tokens`, `total_tokens`,
 * `response_time_ms`, `model` 등의 키를 후보 레코드에서 스캔합니다.
 *
 * @param value - 원시 이벤트 데이터.
 * @returns {@link UsageMetrics} 객체, 또는 메트릭을 찾지 못한 경우 `null`.
 */
export const extractUsageMetrics = (value: unknown): UsageMetrics | null => {
  const metrics: UsageMetrics = {}; // 추출된 메트릭을 저장할 객체

  // 각 후보 레코드에서 토큰 사용량 및 성능 관련 키 스캔
  for (const record of candidateRecords(value)) {
    // 프롬프트 토큰 수 추출 (다양한 키 이름 지원)
    metrics.promptTokens ??= asNumber(
      record.promptTokens ?? record.prompt_tokens ?? record.input_tokens,
    );
    // 완성 토큰 수 추출
    metrics.completionTokens ??= asNumber(
      record.completionTokens ?? record.completion_tokens ?? record.output_tokens,
    );
    // 총 토큰 수 추출
    metrics.totalTokens ??= asNumber(
      record.totalTokens ?? record.total_tokens,
    );
    // 응답 시간(밀리초) 추출
    metrics.responseTimeMs ??= asNumber(
      record.responseTimeMs ?? record.response_time_ms ?? record.elapsed_ms,
    );
    // 사용된 모델 이름 추출
    metrics.model ??= firstString(record, ["model", "model_name"]);
  }

  // 하나 이상의 메트릭이 추출된 경우에만 객체 반환
  return Object.keys(metrics).length ? metrics : null;
};

/**
 * 두 출처 인용 배열을 URL 기준으로 중복 제거하여 병합합니다.
 *
 * 동일한 URL의 나중 항목이 이전 항목을 덮어씁니다.
 *
 * @param current - 이미 표시된 기존 인용.
 * @param next - 병합할 새로 발견된 인용.
 * @returns 결합된, 중복 제거된 인용 배열.
 */
export const mergeSources = (
  current: SourceCitation[] = [],
  next: SourceCitation[] = [],
): SourceCitation[] => {
  // URL을 키로 사용하는 Map으로 중복 제거 (나중 항목이 우선)
  const merged = new Map<string, SourceCitation>();

  // 기존 인용과 새 인용을 순서대로 Map에 추가
  [...current, ...next].forEach((source) => merged.set(source.url, source));

  return [...merged.values()];
};
