/**
 * Next.js API 라우트 핸들러: `GET /api/conversations/[id]/messages`
 *
 * 특정 대화의 메시지 목록 조회 요청을 백엔드로 프록시하며,
 * 세션 쿠키의 JWT를 Bearer 토큰으로, API 키를 `x-api-key`로 전달합니다.
 * @module api/conversations/[id]/messages
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
 * 특정 대화의 메시지 목록을 조회합니다.
 *
 * @param _request - 수신 요청 (본문은 사용되지 않음).
 * @param params - 대상 대화 `id`를 포함하는 라우트 매개변수.
 * @returns 대화 메시지 목록 또는 오류 메시지가 포함된 JSON 응답.
 */
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    // URL 경로에서 대화 ID 추출
    const { id } = await params;
    console.info(`[conversations] 대화 메시지 조회 요청: id=${id}`);
    // 쿠키 저장소에서 세션 쿠키 접근
    const cookieStore = await cookies();
    // 세션 쿠키에서 JWT 토큰 추출
    const token = cookieStore.get("session")?.value;

    // 토큰이 없으면 인증되지 않은 상태 반환
    if (!token) {
      console.info("[conversations] 인증되지 않은 메시지 조회 요청");
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

    // 백엔드에서 특정 대화의 메시지 목록 조회
    console.info(`[conversations] 백엔드에서 대화 메시지 조회 중: id=${id}`);
    const response = await fetch(
      `${BACKEND_URL}/api/conversations/${id}/messages`,
      { headers },
    );

    // 응답 JSON 파싱 후 클라이언트에 전달
    const data = await response.json();
    console.info(
      `[conversations] 대화 메시지 응답: id=${id} status=${response.status}`,
    );
    return NextResponse.json(data, { status: response.status });
  } catch (error) {
    // 백엔드 연결 실패 시 502 프록시 오류 반환
    console.error("[conversations] 대화 메시지 프록시 오류:", error);
    return NextResponse.json(
      { error: "Failed to connect to backend" },
      { status: 502 },
    );
  }
}
