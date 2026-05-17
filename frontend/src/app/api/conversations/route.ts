/**
 * Next.js API 라우트 핸들러: `GET / POST /api/conversations`
 *
 * 대화 목록 조회 및 대화 저장 요청을 백엔드로 프록시하며,
 * 세션 쿠키의 JWT를 Bearer 토큰으로, API 키를 `x-api-key`로 전달합니다.
 * @module api/conversations
 */
import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";

/** 환경 변수에서 확인된 백엔드 기본 URL. */
const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || "http://backend:8000";

/** 서버-백엔드 인증을 위한 API 키. */
const API_KEY =
  process.env.BACKEND_API_KEY || process.env.NEXT_PUBLIC_BACKEND_API_KEY || "";

/**
 * 백엔드 호출을 위한 인증된 요청 헤더를 구성합니다.
 *
 * @param token - JWT 세션 토큰.
 * @returns Authorization 및 선택적 x-api-key가 포함된 헤더 레코드.
 */
function authHeaders(token: string): Record<string, string> {
  const h: Record<string, string> = {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token}`,
  };
  if (API_KEY) {
    h["x-api-key"] = API_KEY;
  }
  return h;
}

/**
 * 사용자의 대화 목록을 조회합니다 (페이지네이션, 날짜 필터 지원).
 *
 * 유효한 세션 쿠키가 필요합니다. JWT는 Bearer 토큰으로 전달됩니다.
 *
 * @returns 대화 목록 또는 오류 메시지가 포함된 JSON 응답.
 */
export async function GET(request: NextRequest) {
  try {
    console.info("[conversations] 대화 목록 조회 요청");
    // 쿠키 저장소에서 세션 쿠키 접근
    const cookieStore = await cookies();
    // 세션 쿠키에서 JWT 토큰 추출
    const token = cookieStore.get("session")?.value;

    // 토큰이 없으면 인증되지 않은 상태 반환
    if (!token) {
      console.info("[conversations] 인증되지 않은 요청");
      return NextResponse.json(
        { error: "Not authenticated" },
        { status: 401 },
      );
    }

    // 백엔드 요청을 위한 인증 헤더 구성
    const headers: Record<string, string> = {
      Authorization: `Bearer ${token}`,
    };
    // API 키가 설정된 경우 헤더에 추가
    if (API_KEY) {
      headers["x-api-key"] = API_KEY;
    }

    // URL에서 페이지네이션 및 날짜 필터 쿼리 파라미터 추출
    const { searchParams } = new URL(request.url);
    // 전달할 쿼리 파라미터 구성 (page, page_size, from_date, to_date)
    const params = new URLSearchParams();
    for (const key of ["page", "page_size", "from_date", "to_date"]) {
      const val = searchParams.get(key);
      if (val) params.set(key, val);
    }
    // 쿼리 문자열이 포함된 백엔드 URL 생성
    const qs = params.toString();
    const url = `${BACKEND_URL}/api/conversations${qs ? `?${qs}` : ""}`;

    // 백엔드에서 대화 목록 조회
    console.info("[conversations] 백엔드에서 대화 목록 조회 중");
    const response = await fetch(url, { headers });

    // 응답 JSON 파싱 후 클라이언트에 전달
    const data = await response.json();
    console.info(
      `[conversations] 대화 목록 응답: status=${response.status}`,
    );
    return NextResponse.json(data, { status: response.status });
  } catch (error) {
    // 백엔드 연결 실패 시 502 프록시 오류 반환
    console.error("[conversations] 대화 목록 프록시 오류:", error);
    return NextResponse.json(
      { error: "Failed to connect to backend" },
      { status: 502 },
    );
  }
}

/**
 * 새로운 대화를 저장합니다.
 *
 * @param request - 대화 제목과 메시지를 포함하는 수신 요청.
 * @returns 저장된 대화 또는 오류 메시지가 포함된 JSON 응답.
 */
export async function POST(request: NextRequest) {
  try {
    console.info("[conversations] 대화 저장 요청");
    // 쿠키 저장소에서 세션 쿠키 접근
    const cookieStore = await cookies();
    // 세션 쿠키에서 JWT 토큰 추출
    const token = cookieStore.get("session")?.value;

    // 토큰이 없으면 인증되지 않은 상태 반환
    if (!token) {
      console.info("[conversations] 인증되지 않은 저장 요청");
      return NextResponse.json(
        { error: "Not authenticated" },
        { status: 401 },
      );
    }

    // 요청 본문에서 대화 제목과 메시지 데이터 추출
    const body = await request.json();
    // 백엔드에 대화 저장 요청 전달
    console.info("[conversations] 백엔드에 대화 저장 중");
    const response = await fetch(`${BACKEND_URL}/api/conversations`, {
      method: "POST",
      headers: authHeaders(token),
      body: JSON.stringify(body),
    });

    // 응답 JSON 파싱 후 클라이언트에 전달
    const data = await response.json();
    console.info(
      `[conversations] 대화 저장 응답: status=${response.status}`,
    );
    return NextResponse.json(data, { status: response.status });
  } catch (error) {
    // 백엔드 연결 실패 시 502 프록시 오류 반환
    console.error("[conversations] 대화 저장 프록시 오류:", error);
    return NextResponse.json(
      { error: "Failed to connect to backend" },
      { status: 502 },
    );
  }
}
