/**
 * Next.js API 라우트 핸들러: `PUT / DELETE /api/admin/users/[userId]`
 *
 * 개별 사용자 수정 및 삭제 작업을 백엔드로 프록시하며,
 * 인증을 위해 세션 JWT와 API 키를 전달합니다.
 * @module api/admin/users/[userId]
 */
import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";

/** 환경 변수에서 확인된 백엔드 기본 URL. */
const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ||
  "http://backend:8000";

/** 서버-백엔드 인증을 위한 API 키. */
const API_KEY =
  process.env.BACKEND_API_KEY || process.env.NEXT_PUBLIC_BACKEND_API_KEY || "";

/**
 * 백엔드 호출을 위한 인증된 요청 헤더를 구성합니다.
 *
 * @param token - JWT 세션 토큰.
 * @returns Content-Type, Authorization 및 선택적 x-api-key가 포함된 헤더 레코드.
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
 * 기존 사용자의 프로필 또는 역할을 수정합니다.
 *
 * @param request - 수정된 사용자 필드를 포함하는 수신 요청.
 * @param params - 대상 `userId`를 포함하는 라우트 매개변수.
 * @returns 수정된 사용자 또는 오류 메시지가 포함된 JSON 응답.
 */
export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ userId: string }> },
) {
  try {
    // URL 경로에서 대상 사용자 ID 추출
    const { userId } = await params;
    console.info(`[admin] User update request: userId=${userId}`);
    // 쿠키 저장소에서 세션 쿠키 접근
    const cookieStore = await cookies();
    // 세션 쿠키에서 JWT 토큰 추출
    const token = cookieStore.get("session")?.value;

    // 토큰이 없으면 인증되지 않은 상태 반환
    if (!token) {
      console.info(`[admin] User update denied: userId=${userId} reason=not_authenticated`);
      return NextResponse.json(
        { error: "Not authenticated" },
        { status: 401 },
      );
    }

    // 요청 본문에서 수정할 사용자 정보 추출
    const body = await request.json();
    // 백엔드에 사용자 수정 요청 전달
    console.info(`[admin] Updating user via backend: userId=${userId}`);
    const response = await fetch(
      `${BACKEND_URL}/api/admin/users/${userId}`,
      {
        method: "PUT",
        headers: authHeaders(token),
        body: JSON.stringify(body),
      },
    );

    // 응답 JSON 파싱 후 클라이언트에 전달
    const data = await response.json();
    console.info(`[admin] User update response: userId=${userId} status=${response.status}`);
    return NextResponse.json(data, { status: response.status });
  } catch (error) {
    // 백엔드 연결 실패 시 502 프록시 오류 반환
    console.error("[admin] User update proxy error:", error);
    return NextResponse.json(
      { error: "Failed to connect to backend" },
      { status: 502 },
    );
  }
}

/**
 * ID로 사용자를 삭제합니다.
 *
 * @param _request - 수신 요청 (본문은 사용되지 않음).
 * @param params - 대상 `userId`를 포함하는 라우트 매개변수.
 * @returns 삭제 확인 또는 오류 메시지가 포함된 JSON 응답.
 */
export async function DELETE(
  _request: NextRequest,
  { params }: { params: Promise<{ userId: string }> },
) {
  try {
    // URL 경로에서 삭제할 사용자 ID 추출
    const { userId } = await params;
    console.info(`[admin] User delete request: userId=${userId}`);
    // 쿠키 저장소에서 세션 쿠키 접근
    const cookieStore = await cookies();
    // 세션 쿠키에서 JWT 토큰 추출
    const token = cookieStore.get("session")?.value;

    // 토큰이 없으면 인증되지 않은 상태 반환
    if (!token) {
      console.info(`[admin] User delete denied: userId=${userId} reason=not_authenticated`);
      return NextResponse.json(
        { error: "Not authenticated" },
        { status: 401 },
      );
    }

    // 백엔드에 사용자 삭제 요청 전달
    console.info(`[admin] Deleting user via backend: userId=${userId}`);
    const response = await fetch(
      `${BACKEND_URL}/api/admin/users/${userId}`,
      {
        method: "DELETE",
        headers: authHeaders(token),
      },
    );

    // 응답 JSON 파싱 후 클라이언트에 전달
    const data = await response.json();
    console.info(`[admin] User delete response: userId=${userId} status=${response.status}`);
    return NextResponse.json(data, { status: response.status });
  } catch (error) {
    // 백엔드 연결 실패 시 502 프록시 오류 반환
    console.error("[admin] User delete proxy error:", error);
    return NextResponse.json(
      { error: "Failed to connect to backend" },
      { status: 502 },
    );
  }
}
