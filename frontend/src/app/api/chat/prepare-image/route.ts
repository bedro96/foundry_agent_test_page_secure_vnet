/**
 * Next.js API 라우트 핸들러: `POST /api/chat/prepare-image`
 *
 * 클라이언트에서 업로드한 이미지를 Azure AI 서비스에 적합한 형식으로 변환합니다.
 * 이미지를 리사이즈/최적화한 후 base64 데이터 URL로 반환합니다.
 * @module api/chat/prepare-image
 */
import { NextResponse } from "next/server";

import { prepareImageForAzure } from "@/lib/images";

/**
 * 업로드된 이미지를 Azure AI용 base64 데이터 URL로 변환합니다.
 *
 * FormData에서 `image` 파일을 추출하고, {@link prepareImageForAzure}를 통해
 * 최적화한 후 base64 인코딩된 이미지 URL을 반환합니다.
 *
 * @param request - `image` 파일이 포함된 multipart/form-data 요청.
 * @returns `{ image_url, originalBytes, outputBytes }` 또는 오류 메시지가 포함된 JSON 응답.
 */
export async function POST(request: Request) {
  try {
    // 멀티파트 폼 데이터에서 이미지 파일 추출
    const formData = await request.formData();
    const file = formData.get("image");

    // 이미지 파일이 없거나 Blob이 아닌 경우 400 오류 반환
    if (!file || !(file instanceof Blob)) {
      return NextResponse.json({ error: "No image file provided." }, { status: 400 });
    }

    // 파일 데이터를 Buffer로 변환
    const arrayBuffer = await file.arrayBuffer();
    const buffer = Buffer.from(arrayBuffer);
    // MIME 타입 결정 (없으면 기본값 image/jpeg)
    const mimeType = file.type || "image/jpeg";

    // Azure AI용으로 이미지 리사이즈 및 최적화 처리
    const result = await prepareImageForAzure(buffer, mimeType);

    // 최적화된 이미지를 Base64 데이터 URL로 변환
    const base64 = result.buffer.toString("base64");
    const imageUrl = `data:${result.mimeType};base64,${base64}`;

    // 이미지 URL과 원본/출력 크기 정보 반환
    return NextResponse.json({
      image_url: imageUrl,
      originalBytes: result.originalBytes,
      outputBytes: result.outputBytes,
    });
  } catch (error) {
    // 이미지 처리 실패 시 400 오류 반환
    const message = error instanceof Error ? error.message : "Image processing failed.";
    return NextResponse.json({ error: message }, { status: 400 });
  }
}
