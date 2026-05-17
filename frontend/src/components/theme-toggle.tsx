/**
 * 다크/라이트 모드 전환 버튼 컴포넌트.
 *
 * `next-themes`의 `useTheme` 훅을 사용하여 현재 테마를 감지하고
 * 클릭 시 반대 테마로 전환합니다.
 * @module theme-toggle
 */
"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";

import { Button } from "@/components/ui/button";

/**
 * 다크/라이트 모드를 토글하는 아이콘 버튼.
 *
 * 현재 테마에 따라 해/달 아이콘을 표시하며,
 * 클릭 시 반대 테마로 전환합니다.
 *
 * @returns 테마 토글 버튼 요소.
 */
export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme(); // 현재 테마와 테마 변경 함수
  const isDark = resolvedTheme === "dark"; // 다크 모드 여부 판별

  return (
    <Button
      aria-label="Toggle theme"
      size="icon"
      variant="outline"
      onClick={() => setTheme(isDark ? "light" : "dark")}
    >
      {isDark ? <Sun className="size-4" /> : <Moon className="size-4" />}
    </Button>
  );
}
