/**
 * Next.js 애플리케이션 구성 파일.
 *
 * 빌드 출력 모드, 이미지 최적화, 원격 이미지 패턴 등
 * Next.js 프레임워크의 핵심 동작을 정의합니다.
 * @module next.config
 */
import type { NextConfig } from "next";

/**
 * Next.js 구성 객체.
 * 배포 환경(Azure Container Apps)에 맞춘 설정을 포함합니다.
 */
const nextConfig: NextConfig = {
  // "standalone" 모드: Docker 컨테이너 배포를 위해 독립 실행 가능한 빌드 출력을 생성합니다.
  // node_modules 없이도 실행 가능한 최소 파일 셋을 생성합니다.
  output: "standalone",

  // 이미지 최적화 설정: Next.js의 <Image> 컴포넌트에서 허용할 외부 이미지 소스를 정의합니다.
  images: {
    // 원격 이미지 패턴: 허용된 외부 이미지 호스트 목록.
    // 보안을 위해 명시적으로 허용된 호스트만 Next.js 이미지 최적화를 사용할 수 있습니다.
    remotePatterns: [
      {
        // Unsplash 이미지 서비스 허용 (배경 이미지 등에 사용)
        protocol: "https",
        hostname: "images.unsplash.com",
      },
    ],
  },
};

// 구성 객체를 기본 내보내기로 제공합니다.
export default nextConfig;
