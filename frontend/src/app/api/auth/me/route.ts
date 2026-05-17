/**
 * Next.js API 라우트 핸들러: `GET /api/auth/me`
 *
 * 현재 세션의 사용자 정보를 반환합니다.
 * 세션 쿠키의 JWT를 검증하여 인증된 사용자 데이터를 제공합니다.
 * @module api/auth/me
 */
import { NextResponse } from "next/server";

import { getSession } from "@/lib/auth";

/**
 * 현재 인증된 사용자 정보를 조회합니다.
 *
 * {@link getSession}을 통해 세션을 검증하고, 유효한 세션이 있으면
 * `userId`, `email`, `role` 정보를 반환합니다.
 *
 * @returns 사용자 정보 또는 인증 오류가 포함된 JSON 응답.
 */
export async function GET() {
  try {
    // 세션 쿠키에서 JWT를 검증하여 현재 사용자 세션 조회
    const session = await getSession();

    // 유효한 세션이 없으면 401 인증 오류 반환
    if (!session) {
      return NextResponse.json({ error: "Not authenticated" }, { status: 401 });
    }

    // 인증된 사용자 정보(ID, 이메일, 역할) 반환
    return NextResponse.json({
      user: {
        userId: session.user_id,
        email: session.email,
        role: session.role,
      },
    });
  } catch (error) {
    // 세션 조회 중 내부 서버 오류 발생 시 500 응답
    console.error("[auth] 세션 조회 오류:", error);
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 },
    );
  }
}
