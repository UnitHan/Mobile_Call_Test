// React 앱 타입 정의

export interface Device {
  platform: 'Android' | 'iOS';
  udid: string;
  name: string;
  connected: boolean;
}

export interface AppInfo {
  id: string;
  name: string;
  package?: string;  // Android
  bundleId?: string;  // iOS
  platform: 'Android' | 'iOS' | 'Both';
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
    package: 'com.lguplus.aicallagent',
    platform: 'Android'
  },
  {
    id: 'aidot',
    name: '에이닷 전화',
    package: 'com.skt.prod.dialer',
    platform: 'Android'
  },
  {
    id: 'samsung_phone',
    name: '삼성 전화',
    package: 'com.samsung.android.dialer',
    platform: 'Android'
  },
  {
    id: 'apple_phone',
    name: 'Apple 전화',
    bundleId: 'com.apple.mobilephone',
    platform: 'iOS'
  },
  {
    id: 'google_phone',
    name: 'Google 전화',
    package: 'com.google.android.dialer',
    platform: 'Android'
  }
];

export const TEST_DURATIONS = [
  { value: 1, label: '1분' },
  { value: 3, label: '3분' },
  { value: 5, label: '5분' },
  { value: 10, label: '10분' }
];

export const AUDIO_PRESETS = [
  { path: 'test_1min.wav', duration: 1, label: '1분 테스트' },
  { path: 'test_3min.wav', duration: 3, label: '3분 테스트' },
  { path: 'test_5min.wav', duration: 5, label: '5분 테스트' },
  { path: 'test_10min.wav', duration: 10, label: '10분 테스트' }
];
