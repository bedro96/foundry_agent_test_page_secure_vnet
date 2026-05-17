/**
 * Next.js API 라우트 핸들러: `POST /api/auth/logout`
 *
 * 세션 쿠키를 삭제하여 사용자를 로그아웃 처리합니다.
 * @module api/auth/logout
 */
import { NextResponse } from "next/server";

import { clearSessionCookie } from "@/lib/auth";

/**
 * 사용자 로그아웃을 처리합니다.
 *
 * {@link clearSessionCookie}를 호출하여 HTTP-only 세션 쿠키를 제거합니다.
 *
 * @returns 성공 메시지 또는 오류 메시지가 포함된 JSON 응답.
 */
export async function POST() {
  try {
    // HTTP-only 세션 쿠키를 삭제하여 사용자 세션 종료
    await clearSessionCookie();
    // 로그아웃 성공 응답 반환
    return NextResponse.json({ message: "Logged out successfully" });
  } catch (error) {
    // 로그아웃 처리 중 내부 서버 오류 발생 시 500 응답
    console.error("[auth] 로그아웃 오류:", error);
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 },
    );
  }
}
