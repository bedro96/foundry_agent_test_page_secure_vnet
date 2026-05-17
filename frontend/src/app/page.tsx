"use client";

/**
 * 메인 랜딩 페이지.
 *
 * 공장 모니터링 시스템의 첫 화면으로, 좌측에 배경 이미지를 표시하고
 * 우측에 로그인 폼과 시스템 소개 콘텐츠를 렌더링합니다.
 * @module page
 */
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { StatusBadges } from "@/components/status-badges";

/**
 * 랜딩 페이지 컴포넌트.
 *
 * 이메일/비밀번호 로그인 폼과 AI 기반 스마트 진단 소개를 포함합니다.
 * 로그인 성공 시 `/chat` 페이지로 리다이렉트합니다.
 */
export default function LandingPage() {
  // 페이지 이동을 위한 Next.js 라우터
  const router = useRouter();
  // 로그인 폼 입력 데이터 (이메일, 비밀번호)
  const [formData, setFormData] = useState({ email: "", password: "" });
  // 로그인 실패 시 표시할 오류 메시지
  const [error, setError] = useState("");
  // 로그인 요청 진행 중 여부
  const [loading, setLoading] = useState(false);

  /**
   * 로그인 폼 제출 핸들러.
   *
   * 백엔드 인증 API를 호출하고 성공 시 채팅 페이지로 이동합니다.
   */
  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    setLoading(true);

    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(formData),
        credentials: "include",
      });
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || data.detail || "Failed to login");
      }

      router.push("/chat");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "An error occurred");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="flex min-h-screen bg-background text-foreground">
      <StatusBadges />
      {/* ── 좌측: 공장 배경 이미지 및 시스템 소개 오버레이 ── */}
      <section className="relative hidden md:flex md:w-1/2">
        <img
          src="/photo-1581091226825-a6a2a5aee158.jpeg"
          alt="Factory monitoring dashboard"
          className="h-full w-full object-cover"
        />
        <div className="absolute inset-0 bg-gradient-to-br from-slate-950/75 via-slate-900/45 to-slate-950/70" />
        <div className="absolute inset-x-0 bottom-0 p-10 text-white">
          <p className="text-sm font-medium uppercase tracking-[0.3em] text-white/75">
            Smart operations
          </p>
          <h1 className="mt-4 max-w-lg text-4xl font-semibold tracking-tight lg:text-5xl">
            Factory Line Monitoring System
          </h1>
          <p className="mt-4 max-w-md text-sm leading-6 text-white/80 lg:text-base">
            Monitor production insights, investigate issues faster, and collaborate with AI-powered support from one workspace.
          </p>
        </div>
      </section>

      {/* ── 우측: 로그인 폼 및 소개 콘텐츠 ── */}
      <section className="flex w-full flex-1 flex-col md:w-1/2">
        {/* 로그인 폼 영역 */}
        <div className="flex justify-center p-4 sm:justify-end sm:p-6 lg:p-8">
          <div className="w-full max-w-xl rounded-2xl border bg-background/95 p-4 shadow-sm backdrop-blur supports-[backdrop-filter]:bg-background/80">
            <form className="flex flex-col gap-3 lg:flex-row lg:items-end" onSubmit={handleSubmit}>
              {/* 이메일 입력 필드 */}
              <div className="grid flex-1 gap-1.5">
                <Label htmlFor="email">Email</Label>
                <Input
                  id="email"
                  type="email"
                  placeholder="you@company.com"
                  value={formData.email}
                  onChange={(event) =>
                    setFormData((current) => ({ ...current, email: event.target.value }))
                  }
                  className="h-9"
                  required
                />
              </div>
              {/* 비밀번호 입력 필드 */}
              <div className="grid flex-1 gap-1.5">
                <Label htmlFor="password">Password</Label>
                <Input
                  id="password"
                  type="password"
                  placeholder="Enter password"
                  value={formData.password}
                  onChange={(event) =>
                    setFormData((current) => ({ ...current, password: event.target.value }))
                  }
                  className="h-9"
                  required
                />
              </div>
              <Button type="submit" className="h-9 shrink-0 px-6" disabled={loading}>
                {loading ? "Signing In..." : "Sign In"}
              </Button>
            </form>
            {/* 회원가입 링크 및 오류 메시지 표시 영역 */}
            <div className="mt-3 flex flex-col gap-2 text-sm sm:flex-row sm:items-center sm:justify-between">
              <p className="text-muted-foreground">
                Don&apos;t have an account?{' '}
                <Link href="/signup" className="font-medium text-primary hover:underline">
                  Sign up
                </Link>
              </p>
              {error ? <p className="text-sm text-destructive">{error}</p> : null}
            </div>
          </div>
        </div>

        {/* AI 기반 스마트 진단 소개 영역 */}
        <div className="flex flex-1 items-center justify-center px-6 py-12 sm:px-10 lg:px-16">
          <div className="max-w-xl space-y-6 text-center sm:text-left">
            <span className="inline-flex rounded-full border border-primary/20 bg-primary/10 px-4 py-1 text-sm font-medium text-primary">
              AI-Powered Smart Diagnosis
            </span>
            <div className="space-y-4">
              <h2 className="text-4xl font-semibold tracking-tight text-balance lg:text-5xl">
                Welcome to your factory operations assistant.
              </h2>
              <p className="text-base leading-7 text-muted-foreground lg:text-lg">
                Sign in to access live chat, source-backed answers, and production support workflows tailored for manufacturing teams.
              </p>
            </div>
            {/* 기능 소개 카드 그리드 */}
            <div className="grid gap-3 text-left text-sm text-muted-foreground sm:grid-cols-2">
              <div className="rounded-2xl border bg-card p-4">
                <p className="font-medium text-foreground">Search-backed diagnosis</p>
                <p className="mt-1 leading-6">
                  Pull in research, operational context, and citations while the assistant streams responses.
                </p>
              </div>
              <div className="rounded-2xl border bg-card p-4">
                <p className="font-medium text-foreground">Real-time response</p>
                <p className="mt-1 leading-6">
                  Keep teams aligned with fast access to troubleshooting, process summaries, and MCP tooling.
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
