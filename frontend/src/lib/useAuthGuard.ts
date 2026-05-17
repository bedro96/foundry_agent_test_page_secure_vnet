"use client";

/**
 * 인증 가드 훅 — 보호된 페이지에서 사용자 인증 상태를 확인합니다.
 *
 * 컴포넌트 마운트 시 `/api/auth/me`를 호출하여 세션을 검증하고,
 * 인증되지 않은 사용자는 메인 페이지(`/`)로 리다이렉트합니다.
 *
 * @module useAuthGuard
 */
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

/** 인증된 사용자 정보 타입. */
interface AuthUser {
  /** 사용자 고유 식별자. */
  userId: string;
  /** 사용자 이메일 주소. */
  email: string;
  /** 사용자 역할 (예: "admin", "user"). */
  role: string;
}

/** useAuthGuard 훅의 반환 타입. */
interface AuthGuardResult {
  /** 인증된 사용자 정보. 인증 확인 전 또는 미인증 시 null. */
  user: AuthUser | null;
  /** 인증 상태 확인 중 여부. true이면 로딩 스피너를 표시해야 합니다. */
  loading: boolean;
}

/**
 * 보호된 페이지에서 인증 상태를 확인하는 클라이언트 훅.
 *
 * 마운트 시 `/api/auth/me` API를 호출하여 세션 쿠키의 JWT를 검증합니다.
 * 인증되지 않은 경우(401) 메인 로그인 페이지(`/`)로 자동 리다이렉트합니다.
 *
 * @returns 인증된 사용자 정보와 로딩 상태를 포함하는 객체.
 *
 * @example
 * ```tsx
 * const { user, loading } = useAuthGuard();
 * if (loading) return <LoadingSpinner />;
 * // user는 인증된 사용자 정보 (null이면 리다이렉트 중)
 * ```
 */
export function useAuthGuard(): AuthGuardResult {
  // 인증된 사용자 상태
  const [user, setUser] = useState<AuthUser | null>(null);
  // 인증 확인 중 여부 (초기값: true)
  const [loading, setLoading] = useState(true);
  // 클라이언트 사이드 라우터 (리다이렉트용)
  const router = useRouter();

  useEffect(() => {
    /** 세션 검증 및 리다이렉트 처리. */
    async function checkAuth() {
      try {
        // 세션 쿠키를 포함하여 현재 사용자 정보 요청
        const res = await fetch("/api/auth/me", { credentials: "include" });

        if (!res.ok) {
          // 인증 실패 (401 등) — 로그인 페이지로 리다이렉트
          // loading을 true로 유지하여 리다이렉트 중 보호된 콘텐츠가 표시되지 않도록 함
          router.replace("/");
          return;
        }

        // 응답에서 사용자 정보 추출
        const data = await res.json();
        setUser(data.user ?? null);
        // 인증 성공 시에만 로딩 상태 해제
        setLoading(false);
      } catch {
        // 네트워크 오류 등 — 로그인 페이지로 리다이렉트
        // loading을 true로 유지하여 보호된 콘텐츠가 표시되지 않도록 함
        router.replace("/");
      }
    }

    void checkAuth();
  }, [router]);

  return { user, loading };
}
