/**
 * Tailwind CSS 유틸리티 헬퍼.
 * @module utils
 */
import { clsx, type ClassValue } from "clsx" // 조건부 클래스 이름 결합 라이브러리
import { twMerge } from "tailwind-merge" // Tailwind CSS 클래스 충돌 해결 라이브러리

/**
 * `clsx`와 `tailwind-merge`를 사용하여 클래스 이름을 병합합니다.
 *
 * 조건부 클래스 로직(clsx)과 Tailwind 충돌 해결(tailwind-merge)을 결합하여
 * 나중에 오는 클래스가 이전 클래스를 올바르게 오버라이드하도록 합니다.
 *
 * @param inputs - clsx가 허용하는 클래스 값, 배열, 또는 조건부 객체.
 * @returns 병합된 단일 클래스 문자열.
 */
export function cn(...inputs: ClassValue[]) {
  // clsx로 조건부 클래스를 결합한 후, twMerge로 Tailwind 충돌 해결
  return twMerge(clsx(inputs))
}
