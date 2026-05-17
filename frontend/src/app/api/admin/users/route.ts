/**
 * Next.js API 라우트 핸들러: `GET /api/admin/users`
 *
 * 관리자 사용자 목록 요청을 백엔드로 프록시하며, 세션 쿠키의 JWT를
 * Bearer 토큰으로, API 키를 `x-api-key`로 전달합니다.
 * @module api/admin/users
 */
import { cookies } from "next/headers";
import { NextResponse } from "next/server";

/** 환경 변수에서 확인된 백엔드 기본 URL. */
const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ||
  "http://backend:8000";

/** 서버-백엔드 인증을 위한 API 키. */
const API_KEY =
  process.env.BACKEND_API_KEY || process.env.NEXT_PUBLIC_BACKEND_API_KEY || "";

/**
 * 모든 사용자 목록 조회 (관리자 전용).
 *
 * 유효한 세션 쿠키가 필요합니다. JWT는 Bearer 토큰으로 전달되어
 * 백엔드에서 호출자의 관리자 역할을 확인할 수 있습니다.
 *
 * @returns 사용자 목록 또는 오류 메시지가 포함된 JSON 응답.
 */
export async function GET() {
  try {
    console.info("[admin] User list request received");
    // 쿠키 저장소에서 세션 쿠키 접근
    const cookieStore = await cookies();
    // 세션 쿠키에서 JWT 토큰 추출
    const token = cookieStore.get("session")?.value;

    // 토큰이 없으면 인증되지 않은 상태 반환
    if (!token) {
      console.info("[admin] User list denied: not authenticated");
      return NextResponse.json(
        { error: "Not authenticated" },
        { status: 401 },
      );
    }

    // 백엔드 요청을 위한 인증 헤더 구성 (Bearer 토큰 + API 키)
    const headers: Record<string, string> = {
      Authorization: `Bearer ${token}`,
    };
    if (API_KEY) {
      headers["x-api-key"] = API_KEY;
    }

    // 백엔드에서 전체 사용자 목록 조회
    console.info("[admin] Fetching user list from backend");
    const response = await fetch(`${BACKEND_URL}/api/admin/users`, {
      headers,
    });

    // 응답 JSON 파싱 후 클라이언트에 전달
    const data = await response.json();
    console.info(`[admin] User list response: status=${response.status}`);
    return NextResponse.json(data, { status: response.status });
  } catch (error) {
    // 백엔드 연결 실패 시 502 프록시 오류 반환
    console.error("[admin] User list proxy error:", error);
    return NextResponse.json(
      { error: "Failed to connect to backend" },
      { status: 502 },
    );
  }
}
