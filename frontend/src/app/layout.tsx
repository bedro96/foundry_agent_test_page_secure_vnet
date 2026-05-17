/**
 * 루트 레이아웃.
 *
 * 전체 애플리케이션의 HTML 구조를 정의하며, 테마 제공자, 네비게이션 바,
 * 토스트 알림 제공자를 포함합니다. Google Geist 폰트를 적용합니다.
 * @module layout
 */
import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { AppNavbar } from "@/components/app-navbar";
import { ThemeProvider } from "@/components/theme-provider";
import { ToastProvider } from "@/components/toast-provider";

import "./globals.css";

/** Geist Sans 폰트 설정 — CSS 변수 `--font-geist-sans`로 참조됩니다. */
const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

/** Geist Mono 폰트 설정 — CSS 변수 `--font-geist-mono`로 참조됩니다. */
const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

/** 페이지 메타데이터 — 브라우저 탭 제목 및 설명. */
export const metadata: Metadata = {
  title: "AI Chat Portal",
  description: "ChatGPT-style frontend for streaming AI answers and MCP testing.",
};

/**
 * 루트 레이아웃 컴포넌트.
 *
 * 모든 페이지를 감싸는 최상위 레이아웃으로, 테마, 네비게이션, 토스트를 제공합니다.
 *
 * @param props - 자식 페이지 요소를 포함하는 props.
 */
export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full bg-background text-foreground">
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          disableTransitionOnChange
          enableSystem
        >
          <div className="flex min-h-screen flex-col bg-background">
            <AppNavbar />
            <div className="flex flex-1 overflow-hidden">{children}</div>
          </div>
          {/* 전역 토스트 알림 */}
          <ToastProvider />
        </ThemeProvider>
      </body>
    </html>
  );
}
