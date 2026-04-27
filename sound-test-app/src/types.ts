// 익시오 통화 테스트 앱 타입 정의

// ── 음원 프로파일 ─────────────────────────────────────────────────────────────

/**
 * 음원 프로파일 — 콘텐츠(뭘 재생·비교할까)만 정의.
 *   S1/S2 : 화자별 테스트 음원
 *   ref   : 정답지 음원(TTS WAV)
 *   script: 정답지 대본 텍스트 (음단절 분석용)
 *
 * 하드웨어 라우팅(출력장치·채널·녹음채널·출력쌍)은
 * 글로벌 설정(speakerConfig_v1)에서 일원 관리합니다.
 */
export interface AudioProfile {
  id: string;
  name: string;
  // 화자별 테스트 음원
  speaker1AudioFile: string;
  speaker2AudioFile: string;
  // 정답지 (화자별 분리)
  refAudioPathS1: string;  // S1(철수/SPEAKER_00) 음원 — TC_01/03에서 Android 수신 녹음의 비교 기준
  refAudioPathS2: string;  // S2(영희/SPEAKER_01) 음원 — TC_01/03에서 iOS 수신 녹음의 비교 기준
  /** @deprecated 하위호환용 — S1/S2 미설정 시 양쪽 공통 정답지로 폴백 */
  refAudioPath?: string;
  scriptPath: string;   // 대본 .txt 파일 경로
}

// ── TC 대시보드 타입 ──────────────────────────────────────────────────────────

export type TcId = "TC_00" | "TC_01" | "TC_02" | "TC_03" | "TC_04";
export type TcStatus = "PASS" | "FAIL" | "ERROR" | "RUNNING" | "QUEUED" | "SCHEDULED";
export type DropoutSeverity = "없음" | "경미" | "보통" | "심각";

/** TC별 설정 — 디바이스 + 프로파일 연결만.
 *  음원·정답지는 profileId가 가리키는 AudioProfile에서,
 *  하드웨어 라우팅은 글로벌 설정에서 가져옵니다. */
export interface TcSpeakerEntry {
  speaker1Device: string;
  speaker2Device: string;
  /** 이 TC에 연결된 프로파일 ID (음원·정답지·대본 결정) */
  profileId: string;
}

export type TcSpeakerConfig = Partial<Record<TcId, TcSpeakerEntry>>;

/** @deprecated TC별 음원만 저장하던 구형 타입 — TcSpeakerConfig 사용 */
export interface TcAudioEntry {
  normalAudio: string;
  phishingAudio: string;
}
export type TcAudioConfig = Partial<Record<TcId, TcAudioEntry>>;

/** @deprecated */
export type TcPhase = 1 | 2;

/** 반복 실행 단위 */
export type RepeatMode = "tc" | "set";

/** 실패 시 동작 */
export type FailAction = "stop" | "continue" | "retry_crash";

/** 반복 테스트 옵션 */
export interface RepeatOptions {
  count: number;           // 반복 횟수 (1~9999)
  mode: RepeatMode;        // tc별 반복 or 세트 반복
  failAction: FailAction;  // 실패 시 동작
}

/** 예약 테스트 옵션 */
export interface ScheduleOptions {
  enabled: boolean;
  scheduledAt: string | null;  // ISO datetime "YYYY-MM-DDTHH:mm" — 지정 일시에 시작
}

/** TC 세션 (단독 또는 반복 묶음) */
export interface TcSession {
  sessionId: string;
  tcIds: TcId[];
  startedAt: string;
  finishedAt: string | null;
  repeatOptions: RepeatOptions | null;
  runIds: string[];        // 포함된 TcResult.runId 목록
}

export interface TcResult {
  runId: string;
  sessionId: string | null;   // 반복 세션 묶음 ID
  repeatIndex: number | null; // 반복 회차 (1-based, null=단독)
  tcId: TcId;
  startedAt: string;          // ISO8601
  finishedAt: string;         // ISO8601
  durationMs: number;
  status: TcStatus;
  phase: TcPhase | null;      // TC_01: Phase 1/2 (완료된 마지막 phase)
  subStatus: string;          // 실시간 진행 메시지 (RUNNING 중)
  iosVisqolMos: number | null;
  androidVisqolMos: number | null;
  snrDb: number | null;
  // 음단절 분석 (TC_01/TC_02 완료 후 자동)
  dropoutCount: number | null;
  dropoutSeverity: DropoutSeverity | null;
  dropoutReportPath: string | null;
  // MOS 보고서 (TC_03 전용)
  mosReportPath: string | null;
  // 단말에서 수집된 음원 파일 (iOS 녹음, Android 통화록)
  extractedAudioPaths: { label: string; path: string }[];
  // 스크린샷
  screenshotPaths: string[];
  // 보이스피싱 감지 결과 (TC_03/TC_04 전용)
  vishingDetected: boolean | null;
  logLines: string[];
  errorMsg: string | null;
  // v2: 플랫폼별 세부 품질 통계
  andDroppedCount:  number | null;
  andDegradedCount: number | null;
  andPoorCount:     number | null;
  andSeverity:      string | null;
  iosDroppedCount:  number | null;
  iosDegradedCount: number | null;
  iosPoorCount:     number | null;
  iosSeverity:      string | null;
  voipDelayMs:      number | null;
  // v3: 디바이스 & 앱 버전
  androidAppVer:    string | null;
  iosAppVer:        string | null;
  androidDevice:    string | null;
  androidOsVer:     string | null;
  iosDevice:        string | null;
  iosOsVer:         string | null;
  profileName:      string | null;
  // v4: 통신사
  carrier:           string | null;
}

// ── Tauri invoke 응답 ──────────────────────────────────────────────────────────

export interface DeviceInfo {
  udid: string;
  platform: string;
  name: string;
  connected: boolean;
}

export interface ConnectionStatus {
  success: boolean;
  message: string;
}

export interface AudioDevice {
  id: number;
  name: string;
  channels: number;
}

export interface EnvItem {
  key: string;
  label: string;
  ok: boolean;
  version: string;
  hint: string;
}

export interface EnvCheckResult {
  items: EnvItem[];
  all_ok: boolean;
  python_env_ready: boolean;
}

// ── 기존 타입 ─────────────────────────────────────────────────────────────────

export interface Device {
  platform: 'Android' | 'iOS';
  udid: string;
  name: string;
  connected: boolean;
}

export interface AppInfo {
  id: string;
  name: string;
  nameEn: string;      // 영문 표시명
  tag: string;         // 파일명용 짧은 태그 (예: ixiO, Samsung, Apple, Adot)
  package?: string;    // Android 패키지명
  activity?: string;   // Android 메인 액티비티 (생략 시 Appium 자동 탐지)
  bundleId?: string;   // iOS 번들 ID
}

/** 통신사 (이동통신망) */
export type CarrierId = 'lguplus' | 'skt' | 'kt';

export interface CarrierInfo {
  id: CarrierId;
  name: string;       // 표시명
  shortName: string;  // 보고서/파일명용 짧은 이름
}

export const SUPPORTED_CARRIERS: CarrierInfo[] = [
  { id: 'lguplus', name: 'LG U+',  shortName: 'LGU+' },
  { id: 'skt',     name: 'SKT',    shortName: 'SKT'  },
  { id: 'kt',      name: 'KT',     shortName: 'KT'   },
];

export const DEFAULT_CARRIER: CarrierId = 'lguplus';

/** 현재 선택된 테스트 앱 설정 (localStorage 저장) */
export interface TargetAppConfig {
  androidAppId: string;  // SUPPORTED_APPS[].id
  iosAppId: string;      // SUPPORTED_APPS[].id
}

export const DEFAULT_APP_CONFIG: TargetAppConfig = {
  androidAppId: 'ixio',
  iosAppId: 'ixio',
};

/** 현재 언어에 따른 앱 표시명 반환 */
export function getAppDisplayName(app: AppInfo, lang: 'ko' | 'en'): string {
  return lang === 'en' ? app.nameEn : app.name;
}

export interface TestConfig {
  caller: {
    device: string;
    app: string;
    phoneNumber: string;
  };
  receiver: {
    device: string;
    app: string;
    phoneNumber: string;
  };
  testDurationMinutes: number;
  audioFile: string;
}

export interface TestResult {
  success: boolean;
  message?: string;
  error?: string;
  summary?: {
    duration: number;
    callStartTime: string;
    callEndTime: string;
    summaryText?: string;
  };
}

export interface TestLog {
  timestamp: string;
  level: 'info' | 'warning' | 'error' | 'success';
  message: string;
}

export const SUPPORTED_APPS: AppInfo[] = [
  {
    id: 'ixio',
    name: '익시오 (LG U+)',
    nameEn: 'ixi-O (LG U+)',
    tag: 'ixiO',
    package: 'com.lguplus.aicallagent',
    activity: '.MainActivity',
    bundleId: 'com.lguplus.aicallagent',
  },
  {
    id: 'aidot',
    name: '에이닷 전화 (SKT)',
    nameEn: 'A. phone (SKT)',
    tag: 'Adot',
    package: 'com.skt.prod.dialer',
    bundleId: 'com.sktelecom.tphone',
  },
  {
    id: 'samsung_phone',
    name: '삼성 전화',
    nameEn: 'Samsung Phone',
    tag: 'Samsung',
    package: 'com.samsung.android.dialer',
  },
  {
    id: 'apple_phone',
    name: 'Apple 전화',
    nameEn: 'Apple Phone',
    tag: 'Apple',
    bundleId: 'com.apple.mobilephone',
  },
];

export const TEST_DURATIONS = [
  { value: 1, label: '1분' },
  { value: 3, label: '3분' },
  { value: 5, label: '5분' },
  { value: 10, label: '10분' }
];
