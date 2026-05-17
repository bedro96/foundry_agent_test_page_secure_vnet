/**
 * Next.js API 라우트 핸들러: `POST /api/auth/login`
 *
 * 로그인 자격 증명을 Python 백엔드로 프록시하고, 반환된 JWT를
 * HTTP-only 세션 쿠키에 저장한 후 사용자 페이로드를 클라이언트에 반환합니다.
 * @module api/auth/login
 */
import { NextRequest, NextResponse } from "next/server";

import { setSessionCookie } from "@/lib/auth";

/** 환경 변수에서 확인된 백엔드 기본 URL. */
const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

/**
 * 자격 증명을 백엔드로 프록시하여 사용자 로그인을 처리합니다.
 *
 * 성공 시 백엔드의 JWT가 HTTP-only 쿠키에 저장되고
 * 사용자 객체가 클라이언트에 반환됩니다. 백엔드 오류는 그대로 전달됩니다.
 *
 * @param request - `{ email, password }`를 포함하는 수신 Next.js 요청.
 * @returns 사용자 페이로드 또는 오류 메시지가 포함된 JSON 응답.
 */
export async function POST(request: NextRequest) {
  try {
    // 요청 본문에서 로그인 자격 증명(이메일, 비밀번호) 추출
    const body = await request.json();

    // 클라이언트 IP 주소 추출 (프록시 헤더 우선, 없으면 직접 연결 IP 사용)
    const forwarded = request.headers.get("x-forwarded-for");
    const clientIp =
      (forwarded ? forwarded.split(",")[0].trim() : null) ||
      request.headers.get("x-real-ip") ||
      "unknown";

    // 로깅용 이메일 추출 (유효하지 않으면 "unknown" 사용)
    const email = typeof body.email === "string" ? body.email : "unknown";
    console.info(`[auth] Login attempt from IP=${clientIp} email=${email}`);

    // 백엔드 로그인 API에 자격 증명 및 클라이언트 IP 전달
    const response = await fetch(`${BACKEND_URL}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...body, client_ip: clientIp }),
    });

    // 백엔드 응답 JSON 파싱
    const data = await response.json();

    // 백엔드 인증 실패 시 오류 응답을 클라이언트에 그대로 전달
    if (!response.ok) {
      console.info(`[auth] Login failed: email=${email} status=${response.status}`);
      return NextResponse.json(data, { status: response.status });
    }

    // JWT 토큰 존재 및 유효성 검증
    if (!data.token || typeof data.token !== "string") {
      console.info(`[auth] Login error: email=${email} reason=no_token_from_backend`);
      return NextResponse.json(
        { error: "Backend did not return a session token" },
        { status: 502 },
      );
    }

    // HTTP-only 세션 쿠키에 JWT 토큰 저장
    await setSessionCookie(data.token);
    console.info(`[auth] Login success: email=${email}`);

    // 사용자 정보를 클라이언트에 반환 (토큰은 쿠키에만 저장)
    return NextResponse.json({
      message: data.message,
      user: data.user,
    });
  } catch (error) {
    // 백엔드 연결 실패 시 502 프록시 오류 반환
    console.error("[auth] Login proxy error:", error);
    return NextResponse.json(
      { error: "Failed to connect to backend" },
      { status: 502 },
    );
  }
}
