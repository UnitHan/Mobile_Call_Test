"""
TC_02: 일반 통화 테스트 (역방향)

시나리오:
  1. speaker1에서 키패드 열고 전화번호 입력 → 발신
  2. speaker2에서 수신
  3. 양쪽 음원 재생 → 오디오 재생 완료 대기
  4. 통화 종료 → 음원 수집

※ speaker1/speaker2 플랫폼은 런타임 감지 — 하드코딩 금지
"""

from tc_base import TcBase


class Tc02(TcBase):
    """TC_02: 일반 통화 테스트 (플랫폼 자동 감지)."""

    def _run_phases(self):
        # Phase 1: 공통 셋업
        if not self.phase_setup():
            return False

        # Phase 2.5: Android sp2 수신 워쳐 (발신 전 시작)
        if self.speaker2_platform == 'Android':
            self.phase_start_android_sp2_watcher()

        # Phase 2: 발신 (플랫폼별)
        if self.speaker1_platform == 'iOS':
            result = self.phase_call_from_ios()
        else:
            result = self.phase_call_from_android()
        if not result:
            return False

        # Phase 3: 수신 (플랫폼별)
        if self.speaker2_platform == 'Android':
            if not self.phase_answer_android_sp2():
                return False
        else:
            if not self.phase_answer_ios_sp2():
                return False

        # Phase 5: 오디오 완료 대기 → 수집 → 결과
        return self.phase_finalize()
