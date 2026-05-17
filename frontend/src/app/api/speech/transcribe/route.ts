/**
 * Next.js API 라우트 핸들러: `POST /api/speech/transcribe`
 *
 * 클라이언트로부터 base64 인코딩된 오디오를 받아 {@link transcribeBackendAudio}를 통해
 * 백엔드 음성 변환 서비스에 위임합니다.
 * @module api/speech/transcribe
 */
import { NextResponse } from "next/server";

import { transcribeBackendAudio } from "@/lib/backend";

/** 음성 변환 엔드포인트에서 기대하는 JSON 본문 형식. */
interface TranscribeRequestBody {
  /** Base64 인코딩된 오디오 데이터. */
  audio_base64?: string;
  /** 오디오의 MIME 타입 (예: `audio/webm`). */
  mime_type?: string;
  /** 선택적 BCP-47 언어 힌트. */
  language?: string;
}

/**
 * 백엔드 음성 서비스로 프록시하여 오디오를 텍스트로 변환합니다.
 *
 * @param request - base64 오디오와 MIME 타입을 포함하는 수신 요청.
 * @returns `{ text, language }` 또는 오류 메시지가 포함된 JSON 응답.
 */
export async function POST(request: Request) {
  try {
    // 요청 본문에서 오디오 데이터와 메타정보 추출
    const body = (await request.json()) as TranscribeRequestBody;
    console.info(`[speech] Transcription request: mime_type=${body.mime_type ?? "(missing)"} language=${body.language ?? "auto"} audio_size=${body.audio_base64?.length ?? 0}`);

    // 필수 필드(오디오 데이터, MIME 타입) 누락 시 400 오류 반환
    if (!body.audio_base64 || !body.mime_type) {
      console.info("[speech] Transcription rejected: missing audio_base64 or mime_type");
      return NextResponse.json(
        { error: "audio_base64 and mime_type are required." },
        { status: 400 },
      );
    }

    // 백엔드 음성 변환 서비스를 통해 오디오를 텍스트로 전사
    const result = await transcribeBackendAudio({
      audio_base64: body.audio_base64,
      mime_type: body.mime_type,
      language: body.language,
    });

    // 전사된 텍스트와 감지된 언어 정보 반환
    console.info(`[speech] Transcription success: language=${result.language} text_length=${result.text.length}`);
    return NextResponse.json({ text: result.text, language: result.language });
  } catch (error) {
    // 전사 실패 시 500 오류 반환
    const message = error instanceof Error ? error.message : "Transcription failed.";
    console.error(`[speech] Transcription error: ${message}`);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
