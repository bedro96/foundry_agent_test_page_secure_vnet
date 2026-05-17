/**
 * Azure AI Foundry 비전 페이로드를 위한 이미지 준비 유틸리티.
 *
 * Azure AI는 ~40 KB 이상의 인라인 이미지 페이로드를 거부하므로,
 * 이 모듈은 해당 제한에 맞추기 위해 sharp를 통한 프로그레시브 JPEG 압축을 제공합니다.
 * @module images
 */
import sharp from "sharp"; // Node.js 고성능 이미지 처리 라이브러리

/** Azure AI Foundry가 인라인 이미지에 허용하는 최대 출력 크기(바이트). */
export const AZURE_AI_VISION_TARGET_MAX_BYTES = 40_000;
/** 처리 전 허용되는 최대 입력 파일 크기(바이트) — OOM(메모리 부족) 방지. */
export const AZURE_AI_VISION_MAX_INPUT_BYTES = 20_000_000;
// 대략 8000x8000 이미지에 해당하는 최대 입력 픽셀 수.
// sharp가 예상치 못한 거대한 이미지를 확장하는 것을 방지합니다.
const SHARP_MAX_INPUT_PIXELS = 64_000_000;

// 너비 후보 배열: 가능한 한 많은 디테일을 유지하기 위해 큰 너비부터 시도하고,
// Azure가 허용하는 작은 페이로드 크기까지 점진적으로 줄입니다.
const JPEG_WIDTH_STEPS = [1280, 768, 512, 384, 320, 256, 192, 128];
// JPEG 품질 단계: 각 너비 후보를 시도한 후에 품질을 단계적으로 감소시킵니다.
const JPEG_QUALITY_STEPS = [70, 60, 50, 40, 32, 24];

/** Azure AI Foundry용 이미지 준비 결과. */
export type PreparedImage = {
  /** 압축된 JPEG 버퍼. */
  buffer: Buffer;
  /** 처리 후 항상 `"image/jpeg"`. */
  mimeType: "image/jpeg";
  /** 이미지가 원본에서 리사이즈/재압축되었는지 여부. */
  resized: boolean;
  /** 원본 입력 버퍼의 크기(바이트). */
  originalBytes: number;
  /** 출력 버퍼의 크기(바이트). */
  outputBytes: number;
};

/**
 * 프로그레시브 리사이즈 시도를 위한 정렬된 너비 후보 목록을 생성합니다.
 *
 * `undefined`(원본 너비)로 시작한 후 {@link JPEG_WIDTH_STEPS}를 통해
 * 순차적으로 줄어들며, 이미 원본 이상인 너비는 건너뜁니다.
 *
 * @param originalWidth - sharp 메타데이터에서 가져온 원본 이미지 너비.
 * @returns 픽셀 너비 배열 (또는 "원본 유지"를 위한 `undefined`).
 */
function buildWidthSteps(originalWidth?: number | null): Array<number | undefined> {
  // 원본 너비가 없거나 유효하지 않으면 모든 후보 너비를 포함
  if (!originalWidth || originalWidth <= 0) {
    return [undefined, ...JPEG_WIDTH_STEPS];
  }

  // undefined(원본 크기 유지)로 시작하여 원본보다 작은 너비만 후보에 추가
  const widths = new Set<number | undefined>([undefined]);
  for (const width of JPEG_WIDTH_STEPS) {
    if (width < originalWidth) {
      widths.add(width);
    }
  }
  return [...widths];
}

/**
 * 표준 안전 제한, 자동 회전, 알파 평탄화가 적용된 sharp 파이프라인을 생성합니다.
 *
 * @param buffer - 처리할 원시 이미지 버퍼.
 * @returns 리사이즈/포맷 작업에 사용할 수 있는 sharp 인스턴스.
 */
function createSharpPipeline(buffer: Buffer) {
  // sharp 인스턴스 생성: 경고 시 실패 처리, 입력 픽셀 수 제한 적용
  return sharp(buffer, {
    failOn: "warning",
    limitInputPixels: SHARP_MAX_INPUT_PIXELS,
  })
    .rotate()              // EXIF 회전 정보에 따른 자동 회전
    .flatten({ background: "#ffffff" }); // 알파 채널 제거 (흰색 배경으로 평탄화)
}

/**
 * Azure AI Foundry의 인라인 크기 제한에 맞추어 이미지 버퍼를 압축하고 리사이즈합니다.
 *
 * 입력이 이미 대상 크기 이하의 JPEG인 경우 그대로 반환됩니다.
 * 그렇지 않으면 출력이 {@link AZURE_AI_VISION_TARGET_MAX_BYTES} 이내에
 * 들어올 때까지 너비와 JPEG 품질을 점진적으로 줄입니다.
 *
 * @param buffer - 원시 이미지 버퍼 (sharp가 지원하는 모든 형식).
 * @param mimeType - 입력 이미지의 MIME 타입.
 * @returns 압축된 JPEG 출력이 포함된 {@link PreparedImage}.
 * @throws {Error} 이미지가 비어있거나, 너무 크거나, 대상 크기로 압축할 수 없을 때.
 */
export async function prepareImageForAzure(
  buffer: Buffer,
  mimeType: string,
): Promise<PreparedImage> {
  // 빈 이미지 파일 검증
  if (buffer.length === 0) {
    throw new Error("Image file is empty.");
  }

  // 입력 파일 크기 상한 검증 (20MB 초과 시 OOM 방지)
  if (buffer.length > AZURE_AI_VISION_MAX_INPUT_BYTES) {
    throw new Error("Image file is too large to process. Send an image smaller than 20 MB.");
  }

  // 이미 JPEG이고 크기 제한 이내인 경우, 변환 없이 원본 그대로 반환
  if (mimeType === "image/jpeg" && buffer.length <= AZURE_AI_VISION_TARGET_MAX_BYTES) {
    return {
      buffer,
      mimeType: "image/jpeg",
      resized: false,
      originalBytes: buffer.length,
      outputBytes: buffer.length,
    };
  }

  // sharp 파이프라인으로 이미지 메타데이터(원본 너비 등) 추출
  const metadata = await createSharpPipeline(buffer).metadata();
  // 원본 너비 기반으로 시도할 리사이즈 너비 후보 생성
  const candidateWidths = buildWidthSteps(metadata.width);

  // 너비와 품질의 모든 조합을 순회하며 크기 제한에 맞는 결과 탐색
  for (const width of candidateWidths) {
    for (const quality of JPEG_QUALITY_STEPS) {
      // 현재 너비/품질 조합으로 JPEG 변환 시도
      const candidate = await createSharpPipeline(buffer)
        .resize({
          width,
          fit: "inside",               // 비율 유지하며 너비 이내로 축소
          withoutEnlargement: true,     // 원본보다 크게 확대하지 않음
        })
        .jpeg({
          quality,
          mozjpeg: true,               // mozjpeg 최적화 엔코더 사용
          chromaSubsampling: "4:2:0",   // 색차 서브샘플링으로 크기 절감
        })
        .toBuffer();

      // 변환 결과가 크기 제한 이내이면 성공적으로 반환
      if (candidate.length <= AZURE_AI_VISION_TARGET_MAX_BYTES) {
        return {
          buffer: candidate,
          mimeType: "image/jpeg",
          resized: true,
          originalBytes: buffer.length,
          outputBytes: candidate.length,
        };
      }
    }
  }

  // 모든 조합으로도 크기 제한에 도달하지 못한 경우 에러 발생
  throw new Error(
    "Unable to compress image to meet Azure AI size requirements. Please try a smaller image (under 20 MB) or reduce the image resolution before sending.",
  );
}