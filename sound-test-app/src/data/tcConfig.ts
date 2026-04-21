import type { TcId } from "../types";

/**
 * TC 표시 ON/OFF 설정
 * - true  → 메인 패널 체크박스 + 설정 모달 사이드바에 표시
 * - false → 숨김 (코드·로직은 유지, UI에서만 비노출)
 *
 * 다시 활성화하려면 해당 TC를 true로 변경하세요.
 */
export const TC_ENABLED: Record<TcId, boolean> = {
  TC_00: true,
  TC_01: true,
  TC_02: true,
  TC_03: true,
  TC_04: true,
};

/**
 * 기능 표시 ON/OFF 설정
 * - VISHING_MODE_BUTTON: true → 오디오 설정 패널에 [🛡 보이스피싱 테스트] 버튼 표시
 *                        false → 버튼 비노출 (기능 코드는 유지)
 */
export const FEATURE_ENABLED = {
  /** 파일 저장 방식 탭의 [마일스톤 이메일 알림] 패널 표시 여부 */
  MILESTONE_EMAIL_PANEL: false,
};
