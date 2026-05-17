/**
 * 애플리케이션 상단 내비게이션 바 컴포넌트.
 *
 * 인증 상태에 따라 네비게이션 링크, 로그인/로그아웃 버튼,
 * 관리자 전용 메뉴를 조건부로 표시합니다.
 * @module app-navbar
 */
"use client";

import { LogOut } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ThemeToggle } from "@/components/theme-toggle";
import { Button, buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** 인증된 사용자 정보 또는 비로그인 상태를 나타내는 타입. */
type User = {
  /** 사용자 고유 식별자. */
  userId: string;
  /** 사용자 이메일 주소. */
  email: string;
  /** 사용자 역할 (예: "admin", "user"). */
  role: string;
} | null;

/** 기본 내비게이션 항목 목록. */
const navItems = [
  { href: "/chat", label: "Chat" },
  { href: "/mcp-test", label: "MCP Test" },
];

/** 관리자 전용 내비게이션 항목. */
const adminNavItem = { href: "/admin", label: "Admin" };

/**
 * 애플리케이션 상단 내비게이션 바.
 *
 * 경로가 변경될 때마다 `/api/auth/me`에서 사용자 정보를 가져오며,
 * 인증 페이지(`/`, `/login`, `/signup`)에서는 렌더링하지 않습니다.
 * 관리자(`role === "admin"`)인 경우 Admin 메뉴가 추가로 표시됩니다.
 *
 * @returns 내비게이션 바 헤더 요소, 또는 인증 페이지에서는 `null`.
 */
export function AppNavbar() {
  const pathname = usePathname(); // 현재 페이지 경로
  const router = useRouter(); // 클라이언트 사이드 라우터
  const [user, setUser] = useState<User>(null); // 인증된 사용자 상태

  useEffect(() => {
    // 컴포넌트 언마운트 시 비동기 작업 취소를 위한 플래그
    let cancelled = false;

    // 서버에서 현재 사용자 정보를 비동기로 로드
    const loadUser = async () => {
      try {
        // 현재 세션의 사용자 정보 API 호출
        const response = await fetch("/api/auth/me", { credentials: "include" });
        if (!response.ok) {
          if (!cancelled) {
            setUser(null);
          }
          return;
        }

        // 응답 데이터에서 사용자 객체 추출
        const data = await response.json();
        if (!cancelled) {
          setUser(data.user || null);
        }
      } catch {
        // 요청 실패 시 사용자 상태를 null로 설정
        if (!cancelled) {
          setUser(null);
        }
      }
    };

    void loadUser();

    // 클린업: 컴포넌트 언마운트 시 비동기 작업 취소
    return () => {
      cancelled = true;
    };
  }, [pathname]);

  /** 로그아웃 처리: API 호출 후 클라이언트 상태를 초기화하고 홈으로 리다이렉트. */
  const handleLogout = async () => {
    try {
      // 서버에 로그아웃 요청 전송 (세션 쿠키 삭제)
      await fetch("/api/auth/logout", {
        method: "POST",
        credentials: "include",
      });
    } catch {
      // 요청 실패 시에도 클라이언트 상태 일관성을 유지하기 위한 최선의 로그아웃 처리.
    }

    // 클라이언트 사용자 상태 초기화 및 홈 페이지로 이동
    setUser(null);
    router.push("/");
    router.refresh();
  };

  // 인증 관련 페이지(랜딩, 로그인, 회원가입)에서는 네비게이션 바 숨김
  const isAuthPage = pathname === "/" || pathname === "/login" || pathname === "/signup";
  if (isAuthPage) {
    return null;
  }

  return (
    <header className="sticky top-0 z-20 border-b bg-background/90 backdrop-blur">
      <div className="mx-auto flex w-full max-w-7xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
        <div>
          <Link href="/chat" className="text-lg font-semibold tracking-tight">
            AI Chat Portal
          </Link>
          <p className="hidden text-sm text-muted-foreground sm:block">
            Streamed answers, citations, and MCP tool exploration.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <nav className="flex items-center gap-1 rounded-full border bg-muted/50 p-1">
            {navItems.map((item) => {
              const active = pathname === item.href;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    buttonVariants({
                      size: "sm",
                      variant: active ? "default" : "ghost",
                    }),
                    "rounded-full",
                  )}
                >
                  {item.label}
                </Link>
              );
            })}
            {user?.role === "admin" && (
              <Link
                href={adminNavItem.href}
                className={cn(
                  buttonVariants({
                    size: "sm",
                    variant: pathname === adminNavItem.href ? "default" : "ghost",
                  }),
                  "rounded-full",
                )}
              >
                {adminNavItem.label}
              </Link>
            )}
          </nav>

          {user ? (
            <>
              <span className="hidden text-sm text-muted-foreground sm:inline">
                {user.email}
              </span>
              <Button onClick={handleLogout} variant="outline" size="sm">
                <LogOut className="mr-1 h-4 w-4" />
                Logout
              </Button>
            </>
          ) : (
            <>
              <Link
                href="/login"
                className={buttonVariants({ size: "sm", variant: "outline" })}
              >
                Login
              </Link>
              <Link
                href="/signup"
                className={buttonVariants({ size: "sm", variant: "default" })}
              >
                Sign Up
              </Link>
            </>
          )}

          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
