/**
 * 테마 프로바이더 컴포넌트.
 *
 * `next-themes`의 `ThemeProvider`를 래핑하여 애플리케이션 전체에
 * 다크/라이트 모드 테마를 제공합니다.
 * @module theme-provider
 */
"use client";

import * as React from "react";
import { ThemeProvider as NextThemesProvider } from "next-themes";

/**
 * 애플리케이션 전체에 테마 컨텍스트를 제공하는 래퍼 컴포넌트.
 *
 * `next-themes`의 `NextThemesProvider`에 모든 props를 전달합니다.
 *
 * @param props - `NextThemesProvider`가 허용하는 모든 props.
 * @returns 테마 프로바이더로 감싸진 자식 요소.
 */
export function ThemeProvider({
  children,
  ...props
}: React.ComponentProps<typeof NextThemesProvider>) {
  return <NextThemesProvider {...props}>{children}</NextThemesProvider>;
}
