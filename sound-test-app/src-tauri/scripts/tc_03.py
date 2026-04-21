"""
TC_03: 보이스피싱 감지 테스트 (정방향)

시나리오:
  TC_01과 동일한 통화 흐름 + 통화 중 보이스피싱 팝업 감지

  1. speaker1에서 키패드 열고 전화번호 입력 → 발신
  2. speaker2에서 수신
  3. 양쪽 음원 재생 + 보이스피싱 팝업 감지 시작
  4. 오디오 재생 완료 대기
  5. 통화 종료 → 음원 수집 + 보이스피싱 감지 결과

※ speaker1/speaker2 플랫폼은 런타임 감지 — 하드코딩 금지
"""

from tc_base import TcBase


class Tc03(TcBase):
    """TC_03: 보이스피싱 감지 테스트 (플랫폼 자동 감지)."""

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

        # Phase 2.7: 발신 직후 오디오 subprocess pre-warm (Android SP2 전용)
        #   → RINGING까지 5~15초 대기하는 동안 subprocess 초기화 완료
        #   → OFFHOOK 즉시 trigger만 보내면 ~100ms 내 재생 시작
        if self.speaker2_platform == 'Android':
            self._clean_audio_started_ts_files()
            self._pre_warmed = self.prepare_audio_players()
            if self._pre_warmed:
                print("  ⚡ [PRE-WARM] 발신 직후 subprocess 생성 — RINGING 대기 중 초기화 진행")
        else:
            self._pre_warmed = False

        # Phase 3: 수신 (플랫폼별)
        if self.speaker2_platform == 'Android':
            if not self.phase_answer_android_sp2():
                return False
        else:
            if not self.phase_answer_ios_sp2():
                return False

        # Phase 4: 보이스피싱 감지
        self.phase_vishing()

        # Phase 5: 오디오 완료 대기 → 수집 → 결과
        return self.phase_finalize()
