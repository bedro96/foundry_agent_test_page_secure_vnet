/**
 * 채팅 입력 컴포넌트.
 *
 * 텍스트 입력, 이미지 첨부, 음성 녹음 및 전사 기능을 제공합니다.
 * Enter 키로 전송, Shift+Enter로 줄바꿈이 가능합니다.
 * @module ChatInput
 */
"use client";

import { LoaderCircle, Mic, Paperclip, SendHorizontal, Square, X } from "lucide-react";
import Image from "next/image";
import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

/** ChatInput 컴포넌트의 props 인터페이스. */
interface ChatInputProps {
  /** 현재 메시지가 처리 중(스트리밍)인지 여부. */
  isLoading: boolean;
  /** 사용자가 메시지를 전송할 때 호출되는 콜백 함수. */
  onSend: (value: string, images?: string[]) => void | Promise<void>;
}

/**
 * 텍스트 입력, 이미지 첨부, 음성 녹음을 지원하는 채팅 입력 영역.
 *
 * - 📎 버튼: 이미지 파일 첨부 (서버에 업로드 후 미리보기 표시).
 * - 🎤 버튼: 음성 녹음 후 Azure Speech API를 통해 텍스트로 전사.
 * - Enter 키: 메시지 전송, Shift+Enter: 줄바꿈.
 *
 * @param props - {@link ChatInputProps} 참조.
 * @returns 채팅 입력 UI 요소.
 */
export function ChatInput({ isLoading, onSend }: ChatInputProps) {
  const [value, setValue] = useState(""); // 텍스트 입력 값 상태
  const [isRecording, setIsRecording] = useState(false); // 음성 녹음 중 상태
  const [isTranscribing, setIsTranscribing] = useState(false); // 음성 전사 중 상태
  const [micError, setMicError] = useState(""); // 마이크 오류 메시지 상태
  const [pendingImages, setPendingImages] = useState<string[]>([]); // 첨부 대기 중인 이미지 URL 목록
  const [isUploadingImage, setIsUploadingImage] = useState(false); // 이미지 업로드 중 상태
  const textareaRef = useRef<HTMLTextAreaElement | null>(null); // 텍스트 입력 필드 DOM 참조
  const fileInputRef = useRef<HTMLInputElement | null>(null); // 파일 선택 입력 DOM 참조
  const recorderRef = useRef<MediaRecorder | null>(null); // MediaRecorder 인스턴스 참조
  const chunksRef = useRef<Blob[]>([]); // 녹음된 오디오 청크 참조
  const streamRef = useRef<MediaStream | null>(null); // 미디어 스트림 참조

  // 텍스트 입력 값이 변경될 때 textarea 높이 자동 조절
  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) {
      return;
    }

    // 높이를 auto로 리셋 후 콘텐츠에 맞게 재계산 (최대 5줄)
    textarea.style.height = "auto";
    const lineHeight = 24; // 한 줄 높이 (px)
    const maxHeight = lineHeight * 5; // 최대 높이 (5줄)
    textarea.style.height = `${Math.min(textarea.scrollHeight, maxHeight)}px`;
  }, [value]);

  /** 미디어 스트림의 모든 트랙을 중지하고 참조를 해제합니다. */
  const cleanupStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

  /** MediaRecorder 인스턴스와 녹음 청크를 초기화합니다. */
  const cleanupRecorder = useCallback(() => {
    recorderRef.current = null;
    chunksRef.current = [];
  }, []);

  // 컴포넌트 언마운트 시 MediaRecorder와 미디어 스트림 리소스 정리
  useEffect(() => {
    return () => {
      const recorder = recorderRef.current;
      // 활성 녹음이 있으면 이벤트 핸들러를 제거하고 중지
      if (recorder && recorder.state !== "inactive") {
        recorder.onstop = null;
        recorder.onerror = null;
        recorder.stop();
      }
      cleanupStream();
      cleanupRecorder();
    };
  }, [cleanupRecorder, cleanupStream]);

  // 마이크 오류 메시지를 3초 후 자동으로 해제
  useEffect(() => {
    if (!micError) {
      return;
    }

    const timeoutId = window.setTimeout(() => setMicError(""), 3000);
    return () => window.clearTimeout(timeoutId);
  }, [micError]);

  /** 입력된 텍스트와 첨부 이미지를 전송하고 입력 필드를 초기화합니다. */
  const submit = async () => {
    const nextValue = value.trim();
    if (!nextValue || isLoading || isRecording || isTranscribing) {
      return;
    }

    const images = pendingImages.length > 0 ? [...pendingImages] : undefined;
    setPendingImages([]);
    await onSend(nextValue, images);
    setValue("");
  };

  /** 선택된 이미지 파일을 서버에 업로드하고 미리보기 URL을 저장합니다. */
  const handleImageSelect = useCallback(async (file: File) => {
    setIsUploadingImage(true);
    setMicError("");

    try {
      const formData = new FormData();
      formData.append("image", file);

      const response = await fetch("/api/chat/prepare-image", {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const payload = (await response.json().catch(() => null)) as { error?: string } | null;
        throw new Error(payload?.error || `Image upload failed (${response.status}).`);
      }

      const payload = (await response.json()) as { image_url: string };
      setPendingImages((current) => [...current, payload.image_url]);
    } catch (error) {
      setMicError(error instanceof Error ? error.message : "Image upload failed.");
    } finally {
      setIsUploadingImage(false);
    }
  }, []);

  /** 지정된 인덱스의 첨부 이미지를 제거합니다. */
  const removeImage = useCallback((index: number) => {
    setPendingImages((current) => current.filter((_, i) => i !== index));
  }, []);

  /** 녹음 완료 후 오디오를 Base64로 변환하여 전사 API에 전송합니다. */
  const handleRecordingComplete = useCallback(async (recordedChunks: Blob[], mimeType: string) => {
    cleanupStream();
    cleanupRecorder();

    const audioBlob = new Blob(recordedChunks, { type: mimeType || "audio/webm" });

    if (!audioBlob.size) {
      setMicError("No audio recorded.");
      setIsTranscribing(false);
      return;
    }

    try {
      const audioBase64 = await blobToBase64(audioBlob);
      const response = await fetch("/api/speech/transcribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          audio_base64: audioBase64,
          mime_type: audioBlob.type || "audio/webm",
          language: "ko-KR",
        }),
      });

      if (!response.ok) {
        const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
        throw new Error(payload?.detail || `Transcription failed with status ${response.status}.`);
      }

      const payload = (await response.json()) as { language?: string; text?: string };
      const transcript = payload.text?.trim();

      if (!transcript) {
        setMicError("No speech detected.");
        return;
      }

      setIsTranscribing(false);
      await onSend(transcript);
    } catch (error) {
      setMicError(error instanceof Error ? error.message : "Transcription failed.");
    } finally {
      setIsTranscribing(false);
      setIsRecording(false);
    }
  }, [cleanupRecorder, cleanupStream, onSend]);

  /** 진행 중인 녹음을 중지하고 전사를 시작합니다. */
  const stopRecording = useCallback(() => {
    const recorder = recorderRef.current;
    if (!recorder) {
      cleanupStream();
      cleanupRecorder();
      setIsRecording(false);
      setIsTranscribing(false);
      return;
    }

    if (recorder.state !== "inactive") {
      setIsTranscribing(true);
      recorder.stop();
    } else {
      cleanupStream();
      cleanupRecorder();
      setIsTranscribing(false);
    }

    setIsRecording(false);
  }, [cleanupRecorder, cleanupStream]);

  /** 마이크 접근 권한을 요청하고 음성 녹음을 시작합니다. */
  const startRecording = useCallback(async () => {
    setMicError("");

    if (isLoading || isTranscribing) {
      return;
    }

    if (typeof window === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      setMicError("Microphone access requires HTTPS or localhost.");
      return;
    }

    if (typeof MediaRecorder === "undefined") {
      setMicError("This browser does not support audio recording.");
      return;
    }

    try {
      // 마이크 접근 권한 요청 및 오디오 스트림 획득
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      // 브라우저가 지원하는 최적의 오디오 MIME 타입 결정
      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : MediaRecorder.isTypeSupported("audio/webm")
          ? "audio/webm"
          : "";

      // MediaRecorder 인스턴스 생성 및 녹음 청크 배열 초기화
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      const recordedChunks: Blob[] = [];
      let didRecorderError = false; // 녹음 오류 발생 여부 추적

      chunksRef.current = recordedChunks;
      recorderRef.current = recorder;

      // 데이터가 수신되면 녹음 청크 배열에 추가
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          recordedChunks.push(event.data);
        }
      };
      // 녹음 오류 발생 시 리소스 정리 및 오류 메시지 표시
      recorder.onerror = () => {
        didRecorderError = true;
        setMicError("Recording failed. Please try again.");
        setIsRecording(false);
        setIsTranscribing(false);
        cleanupStream();
        cleanupRecorder();
      };
      // 녹음 중지 시 오류가 없으면 전사 처리 시작
      recorder.onstop = () => {
        if (didRecorderError) {
          return;
        }
        void handleRecordingComplete(recordedChunks, recorder.mimeType || mimeType || "audio/webm");
      };

      // 녹음 시작
      recorder.start();
      setIsRecording(true);
    } catch (error) {
      // 마이크 접근 실패 시 리소스 정리 및 오류 메시지 설정
      cleanupStream();
      cleanupRecorder();

      // 권한 거부와 기타 오류를 구분하여 메시지 생성
      const message =
        error instanceof DOMException && error.name === "NotAllowedError"
          ? "Microphone access was denied."
          : error instanceof Error
            ? error.message
            : "Unable to access the microphone.";

      setMicError(message);
    }
  }, [
    cleanupRecorder,
    cleanupStream,
    handleRecordingComplete,
    isLoading,
    isTranscribing,
  ]);

  /** 녹음 상태를 토글합니다 — 녹음 중이면 중지, 아니면 시작. */
  const toggleRecording = useCallback(() => {
    if (isLoading || isTranscribing) {
      return;
    }

    if (isRecording) {
      stopRecording();
      return;
    }

    void startRecording();
  }, [isLoading, isRecording, isTranscribing, startRecording, stopRecording]);

  return (
    <div className="rounded-2xl border bg-background p-3 shadow-sm">
      {micError ? (
        <div className="mb-2 rounded-lg border border-destructive/20 bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {micError}
        </div>
      ) : null}
      {pendingImages.length > 0 ? (
        <div className="mb-2 flex flex-wrap gap-2">
          {pendingImages.map((url, index) => (
            <div key={index} className="group relative inline-block">
              <Image
                src={url}
                alt={`Attached image ${index + 1}`}
                width={64}
                height={64}
                className="size-16 rounded-lg border object-cover"
                unoptimized
              />
              <button
                type="button"
                className="absolute -right-1.5 -top-1.5 flex size-5 items-center justify-center rounded-full bg-destructive text-destructive-foreground shadow-sm opacity-0 transition group-hover:opacity-100"
                onClick={() => removeImage(index)}
                aria-label={`Remove image ${index + 1}`}
              >
                <X className="size-3" />
              </button>
            </div>
          ))}
        </div>
      ) : null}
      <div className="flex items-end gap-3">
        <Textarea
          ref={textareaRef}
          className="max-h-32 min-h-12 resize-none border-0 bg-transparent px-0 py-2 shadow-none focus-visible:ring-0"
          disabled={isLoading || isRecording || isTranscribing}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void submit();
            }
          }}
          placeholder="Ask anything…"
          rows={1}
          value={value}
        />
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          className="hidden"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) {
              void handleImageSelect(file);
            }
            event.target.value = "";
          }}
        />
        <Button
          aria-label="Attach image"
          disabled={isLoading || isRecording || isTranscribing || isUploadingImage}
          onClick={() => fileInputRef.current?.click()}
          size="icon"
          title="Attach image"
          type="button"
          variant="outline"
        >
          {isUploadingImage ? (
            <LoaderCircle className="size-4 animate-spin" />
          ) : (
            <Paperclip className="size-4" />
          )}
        </Button>
        <Button
          aria-label={
            isTranscribing ? "Transcribing audio" : isRecording ? "Stop recording" : "Record voice"
          }
          className={isRecording ? "animate-pulse border-destructive/40 bg-destructive/10 text-destructive hover:bg-destructive/20" : ""}
          disabled={isLoading || isTranscribing}
          onClick={toggleRecording}
          size="icon"
          title={
            isTranscribing ? "Transcribing..." : isRecording ? "Stop recording" : "Record voice"
          }
          type="button"
          variant={isRecording ? "destructive" : "outline"}
        >
          {isTranscribing ? (
            <LoaderCircle className="size-4 animate-spin" />
          ) : isRecording ? (
            <Square className="size-4 fill-current" />
          ) : (
            <Mic className="size-4" />
          )}
        </Button>
        <Button
          disabled={isLoading || isRecording || isTranscribing || !value.trim()}
          onClick={() => void submit()}
        >
          <SendHorizontal className="size-4" />
          Send
        </Button>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        Press Enter to send, Shift+Enter for a new line. Click 📎 to attach images, 🎤 to dictate.
      </p>
    </div>
  );
}

/**
 * Blob 데이터를 Base64 문자열로 변환합니다.
 *
 * `FileReader`를 사용하여 데이터 URI에서 Base64 부분만 추출합니다.
 *
 * @param blob - 변환할 Blob 객체.
 * @returns Base64로 인코딩된 문자열.
 */
function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => {
      const result = typeof reader.result === "string" ? reader.result : "";
      resolve(result.split(",")[1] || "");
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}
