/**
 * Next.js API 라우트 핸들러: `POST /api/auth/signup`
 *
 * 회원가입 데이터를 Python 백엔드로 프록시하고 결과를 반환합니다.
 * 로그인과 달리 회원가입은 세션 쿠키를 설정하지 않습니다 — 사용자는
 * 성공적인 등록 후 별도로 로그인해야 합니다.
 * @module api/auth/signup
 */
import { NextRequest, NextResponse } from "next/server";

/** 환경 변수에서 확인된 백엔드 기본 URL. */
const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

/**
 * 회원가입 페이로드를 백엔드로 프록시하여 사용자 등록을 처리합니다.
 *
 * @param request - 등록 필드를 포함하는 수신 Next.js 요청.
 * @returns 백엔드의 성공 또는 오류 페이로드를 반영하는 JSON 응답.
 */
export async function POST(request: NextRequest) {
  try {
    // 요청 본문에서 회원가입 정보(이메일, 비밀번호, 이름 등) 추출
    const body = await request.json();

    // 클라이언트 IP 주소 추출 (프록시 헤더 우선, 없으면 직접 연결 IP 사용)
    const forwarded = request.headers.get("x-forwarded-for");
    const clientIp =
      (forwarded ? forwarded.split(",")[0].trim() : null) ||
      request.headers.get("x-real-ip") ||
      "unknown";

    // 로깅용 이메일 추출 (유효하지 않으면 "unknown" 사용)
    const email = typeof body.email === "string" ? body.email : "unknown";
    console.info(`[auth] Signup attempt from IP=${clientIp} email=${email}`);

    // 백엔드 회원가입 API에 등록 정보 및 클라이언트 IP 전달
    const response = await fetch(`${BACKEND_URL}/api/auth/signup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...body, client_ip: clientIp }),
    });

    // 백엔드 응답 JSON 파싱
    const data = await response.json();
    // 성공/실패 여부에 따라 로그 기록
    if (response.ok) {
      console.info(`[auth] Signup success: email=${email} status=${response.status}`);
    } else {
      console.info(`[auth] Signup failed: email=${email} status=${response.status}`);
    }
    // 백엔드 응답을 클라이언트에 그대로 전달
    return NextResponse.json(data, { status: response.status });
  } catch (error) {
    // 백엔드 연결 실패 시 502 프록시 오류 반환
    console.error("[auth] Signup proxy error:", error);
    return NextResponse.json(
      { error: "Failed to connect to backend" },
      { status: 502 },
    );
  }
}
