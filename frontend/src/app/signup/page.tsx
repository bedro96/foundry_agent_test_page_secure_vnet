"use client";

/**
 * 회원가입 페이지.
 *
 * 사용자 이름, 이메일, 비밀번호를 입력받아 새 계정을 생성하는 폼을 렌더링합니다.
 * 배경에 공장 이미지를 표시하고, 비밀번호 확인 실시간 검증을 제공합니다.
 * @module signup/page
 */
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/**
 * 회원가입 페이지 컴포넌트.
 *
 * 사용자 정보를 백엔드 회원가입 API로 전송하고,
 * 성공 시 `/login` 페이지로 리다이렉트합니다.
 */
export default function SignUpPage() {
  // 페이지 이동을 위한 Next.js 라우터
  const router = useRouter();
  // 회원가입 폼 입력 데이터 (사용자 이름, 이메일, 비밀번호)
  const [formData, setFormData] = useState({
    username: "",
    email: "",
    password: "",
  });
  // 비밀번호 확인 입력 값
  const [confirmPassword, setConfirmPassword] = useState("");
  // 회원가입 실패 시 표시할 오류 메시지
  const [error, setError] = useState("");
  // 회원가입 요청 진행 중 여부
  const [loading, setLoading] = useState(false);

  /** 비밀번호 확인 필드가 원본과 일치하는지 실시간 검증. */
  const passwordsMatch =
    confirmPassword.length > 0 && formData.password === confirmPassword;

  /**
   * 회원가입 폼 제출 핸들러.
   *
   * 비밀번호 일치를 확인한 후 백엔드 회원가입 API를 호출합니다.
   */
  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError("");

    if (formData.password !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }

    setLoading(true);

    try {
      const response = await fetch("/api/auth/signup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(formData),
        credentials: "include",
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || data.detail || "Failed to sign up");
      }

      router.push("/login");
    } catch (err) {
      setError(err instanceof Error ? err.message : "An error occurred");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* ── 전체 화면 배경 이미지 및 블러 오버레이 ── */}
      <div className="absolute inset-0">
        <Image
          src="/background.png"
          alt="Factory background"
          fill
          sizes="100vw"
          className="object-cover"
          priority
        />
        <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" />
      </div>
      {/* 우측 상단 테마 전환 버튼 */}
      <div className="fixed top-4 right-4 z-10">
        <ThemeToggle />
      </div>
      {/* ── 회원가입 카드 폼 ── */}
      <Card className="relative z-10 w-full max-w-md shadow-2xl border-primary/20 bg-background/95 backdrop-blur ring-1 ring-primary/10 m-4">
        <CardHeader>
          <CardTitle>Sign Up</CardTitle>
          <CardDescription>
            Create a new account to get started
          </CardDescription>
        </CardHeader>
        <form onSubmit={handleSubmit}>
          <CardContent className="space-y-4">
            {/* 오류 메시지 표시 영역 */}
            {error ? (
              <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
                {error}
              </div>
            ) : null}
            {/* 사용자 이름 입력 필드 */}
            <div className="space-y-2">
              <Label htmlFor="username">Username</Label>
              <Input
                id="username"
                type="text"
                placeholder="Enter your username"
                value={formData.username}
                onChange={(event) =>
                  setFormData({ ...formData, username: event.target.value })
                }
                required
              />
            </div>
            {/* 이메일 입력 필드 */}
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                placeholder="Enter your email"
                value={formData.email}
                onChange={(event) =>
                  setFormData({ ...formData, email: event.target.value })
                }
                required
              />
            </div>
            {/* 비밀번호 입력 필드 */}
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                placeholder="Enter your password"
                value={formData.password}
                onChange={(event) =>
                  setFormData({ ...formData, password: event.target.value })
                }
                required
              />
            </div>
            {/* 비밀번호 확인 입력 필드 (실시간 일치 검증 포함) */}
            <div className="space-y-2">
              <Label htmlFor="confirmPassword">Confirm Password</Label>
              <Input
                id="confirmPassword"
                type="password"
                placeholder="Re-enter your password"
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                className={
                  confirmPassword.length > 0
                    ? passwordsMatch
                      ? "border-green-500 focus-visible:ring-green-500"
                      : "border-destructive focus-visible:ring-destructive"
                    : ""
                }
                required
              />
              {confirmPassword.length > 0 ? (
                <p
                  className={`text-xs ${
                    passwordsMatch ? "text-green-500" : "text-destructive"
                  }`}
                >
                  {passwordsMatch
                    ? "Passwords match ✓"
                    : "Passwords do not match"}
                </p>
              ) : null}
            </div>
          </CardContent>
          {/* 제출 버튼 및 로그인 페이지 링크 */}
          <CardFooter className="flex flex-col space-y-4">
            <Button
              type="submit"
              className="w-full"
              disabled={loading || formData.password !== confirmPassword}
            >
              {loading ? "Creating account..." : "Sign Up"}
            </Button>
            <p className="text-center text-sm text-muted-foreground">
              Already have an account?{" "}
              <Link href="/login" className="text-primary hover:underline">
                Login
              </Link>
            </p>
          </CardFooter>
        </form>
      </Card>
    </div>
  );
}
