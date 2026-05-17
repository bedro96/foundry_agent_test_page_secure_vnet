/**
 * Next.js API 라우트에서 JWT 쿠키 관리를 위한 인증 유틸리티.
 *
 * JWT는 Python 백엔드에서 발급되며 HTTP-only 쿠키에 저장됩니다.
 * 이 헬퍼들은 해당 쿠키를 설정, 읽기(검증 없이 디코딩), 삭제합니다.
 * @module auth
 */
import { cookies } from "next/headers"; // Next.js 서버 측 쿠키 접근 API

/** HTTP-only 세션 쿠키의 이름. */
const SESSION_COOKIE = "session";
/** 쿠키 최대 수명(초 단위, 24시간 = 86,400초). */
const COOKIE_MAX_AGE = 60 * 60 * 24;

/** JWT 세션 쿠키에서 추출한 디코딩된 사용자 페이로드. */
export interface SessionUser {
  /** 백엔드 데이터베이스의 고유 사용자 식별자. */
  user_id: string;
  /** 사용자의 이메일 주소. */
  email: string;
  /** 인증 역할 (예: `"admin"`, `"user"`). */
  role: string;
}

/**
 * JWT 토큰으로 세션 쿠키를 설정합니다.
 *
 * @param token - 백엔드 로그인 엔드포인트에서 반환된 JWT 문자열.
 */
export async function setSessionCookie(token: string): Promise<void> {
  console.info("[auth] Setting session cookie");
  // Next.js 쿠키 스토어 인스턴스 획득
  const cookieStore = await cookies();
  // JWT 토큰을 HTTP-only 쿠키로 설정 (보안 옵션 적용)
  cookieStore.set(SESSION_COOKIE, token, {
    httpOnly: true,                                    // JavaScript에서 접근 불가 (XSS 방지)
    secure: process.env.NODE_ENV === "production",     // 프로덕션에서만 HTTPS 강제
    sameSite: "lax",                                   // CSRF 방지를 위한 SameSite 정책
    path: "/",                                         // 모든 경로에서 쿠키 접근 가능
    maxAge: COOKIE_MAX_AGE,                            // 24시간 후 만료
  });
}

/**
 * 세션 쿠키를 읽고 암호학적 검증 없이 JWT 페이로드를 디코딩합니다.
 *
 * 백엔드가 토큰의 유일한 발급자이자 검증자입니다 — 이 헬퍼는
 * 클라이언트 측 렌더링 결정을 위해 페이로드 섹션만 base64 디코딩합니다.
 *
 * @returns 디코딩된 세션 사용자, 또는 쿠키가 없거나 만료되었거나 형식이 잘못된 경우 `null`.
 */
export async function getSession(): Promise<SessionUser | null> {
  // Next.js 쿠키 스토어에서 세션 쿠키 읽기
  const cookieStore = await cookies();
  const token = cookieStore.get(SESSION_COOKIE)?.value;

  // 쿠키가 존재하지 않으면 미인증 상태
  if (!token) {
    console.info("[auth] No session cookie found");
    return null;
  }

  try {
    // JWT의 세 부분(header.payload.signature)에서 페이로드(두 번째 부분) 추출
    const payloadBase64 = token.split(".")[1];
    if (!payloadBase64) {
      console.info("[auth] Session token has no payload segment");
      return null;
    }

    // Base64url 인코딩된 페이로드를 디코딩하여 JSON으로 파싱
    const payload = JSON.parse(
      Buffer.from(payloadBase64, "base64url").toString("utf-8"),
    ) as Partial<SessionUser> & { exp?: number };

    // JWT 만료 시간(exp) 검증: 현재 시간보다 과거이면 만료됨
    if (payload.exp && payload.exp * 1000 < Date.now()) {
      console.info(`[auth] Session expired for user=${payload.email ?? "unknown"}`);
      return null;
    }

    // 페이로드 구조 검증: 필수 필드(user_id, email, role)의 타입 확인
    if (
      typeof payload.user_id !== "string" ||
      typeof payload.email !== "string" ||
      typeof payload.role !== "string"
    ) {
      console.info("[auth] Session token has invalid payload structure");
      return null;
    }

    console.info(`[auth] Session verified for user=${payload.email}`);
    // 검증 통과한 사용자 정보 반환
    return {
      user_id: payload.user_id,
      email: payload.email,
      role: payload.role,
    };
  } catch {
    // JSON 파싱 실패 등 예외 발생 시 무효한 토큰으로 처리
    console.info("[auth] Session verification failed — invalid token");
    return null;
  }
}

/**
 * 세션 쿠키를 삭제하여 사용자를 로그아웃시킵니다.
 */
export async function clearSessionCookie(): Promise<void> {
  console.info("[auth] Clearing session cookie");
  // 쿠키 스토어에서 세션 쿠키를 삭제하여 로그아웃 처리
  const cookieStore = await cookies();
  cookieStore.delete(SESSION_COOKIE);
}
