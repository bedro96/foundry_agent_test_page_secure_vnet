"use client";

/**
 * react-toastify 토스트 컨테이너 래퍼.
 *
 * `next-themes`의 현재 테마에 따라 자동으로 다크/라이트 모드 전환합니다.
 * 앱 레이아웃에서 한 번만 렌더링하면 전역 토스트 알림을 사용할 수 있습니다.
 * @module toast-provider
 */
import { ToastContainer } from "react-toastify";
import "react-toastify/dist/ReactToastify.css";
import { useTheme } from "next-themes";

/**
 * 전역 토스트 알림 컨테이너를 렌더링하는 프로바이더 컴포넌트.
 *
 * `resolvedTheme`에 따라 토스트의 다크/라이트 모드를 자동 전환합니다.
 *
 * @returns react-toastify `ToastContainer` 요소.
 */
export function ToastProvider() {
  const { resolvedTheme } = useTheme(); // 현재 적용된 테마 (다크/라이트)

  return (
    <ToastContainer
      position="top-right"
      autoClose={4000}
      hideProgressBar={false}
      newestOnTop
      closeOnClick
      pauseOnFocusLoss
      draggable
      pauseOnHover
      theme={resolvedTheme === "dark" ? "dark" : "light"}
    />
  );
}
