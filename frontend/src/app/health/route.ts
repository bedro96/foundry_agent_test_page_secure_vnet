import { NextResponse } from "next/server";

/** Azure Container Apps 상태 프로브 — 앱이 실행 중일 때 HTTP 200을 반환합니다. */
export async function GET() {
  // 상태 확인 응답 반환 (ACA 헬스체크용)
  return NextResponse.json({ status: "ok" }, { status: 200 });
}
