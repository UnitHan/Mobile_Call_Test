#!/usr/bin/env python3
"""
ixi-O 음단절(오디오 드롭아웃) 감지 가능성 분석
"""

import re
import sys
import statistics
from collections import defaultdict

LOG_FILE = "log_new.txt"

# ──────────────────────────────────────────────
# 패턴 정의
# ──────────────────────────────────────────────

# 1. TX InsertESData 처리 시간 (마이크 → 엔진 버퍼 삽입 지연)
PAT_INSERT_TIME   = re.compile(r"TX InsertESData OK, time=(\d+\.?\d*)ms")

# 2. sendLiveBuffer: tx_count, rx_count
PAT_LIVE_BUFFER   = re.compile(
    r"ENGINE_sendLiveBuffer.*?tx_count.*?(\d+).*?rx_count.*?(\d+).*?eleaped.*?(\d+)"
)
PAT_LIVE_BUFFER2  = re.compile(
    r"ENGINE_sendLiveBuffer.+?\"tx_count\":\s*\"(\d+)\".+?\"rx_count\":\s*\"(\d+)\".+?\"eleaped\":\s*\"(\d+)\""
)

# 3. SendPackets totalCount (누적 전송 패킷)
PAT_SEND_PKTS     = re.compile(
    r"ENGINE_SendPackets.+?\"totalCount\":\s*\"(\d+)\""
)

# 4. ReceivePackets validCount / totalCount (수신 패킷 손실률)
PAT_RECV_PKTS     = re.compile(
    r"ENGINE_ReceivePackets.+?\"totalCount\":\s*\"(\d+)\".+?\"validCount\":\s*\"(\d+)\""
)
PAT_RECV_PKTS2    = re.compile(
    r"ENGINE_ReceivePackets.+?\"validCount\":\s*\"(\d+)\".+?\"totalCount\":\s*\"(\d+)\""
)

# 5. 타임스탬프
PAT_TS            = re.compile(r"(\d{2}:\d{2}:\d{2}\.\d+)")

# 6. ENGINE_sendReport: packetCount, OctetCount
PAT_SEND_REPORT   = re.compile(
    r"ENGINE_sendReport.+?\"packetCount\":\s*\"(\d+)\".+?\"OctetCount\":\s*\"(\d+)\""
)

# 7. ReceiveReport: 있으면 jitter, lost 등
PAT_RECV_REPORT   = re.compile(r"ENGINE_ReceiveReport.+")

# 8. CAPTURE InsertESData (마이크 캡처 -> 버퍼)
PAT_CAPTURE_ERR   = re.compile(r"CAPTURE InsertESData\s+(OK|FAIL|SKIP|DROP)")

# 9. RENDER (스피커 재생 버퍼)
PAT_RENDER_ERR    = re.compile(r"\[RENDER\].+(FAIL|ERROR|DROP|silent|underrun)", re.I)

# 10. micHealthCheck - buffer_count
PAT_MIC_HEALTH    = re.compile(
    r"ENGINE_micHe[ae]lthCheck.+?\"buffer_count\":\s*\"(\d+)\""
)

# ──────────────────────────────────────────────
# 데이터 수집
# ──────────────────────────────────────────────

insert_times    = []   # (ts, ms)
live_buffers    = []   # (ts, tx, rx, elapsed_ms)
send_pkts       = []   # (ts, totalCount)
recv_pkts       = []   # (ts, totalCount, validCount)
send_reports    = []   # (ts, packetCount, octetCount)
capture_results = defaultdict(int)
render_errors   = []
mic_health      = []   # (ts, buffer_count)

print(f"[분석] {LOG_FILE} 파싱 중...")

with open(LOG_FILE, encoding="utf-8", errors="replace") as f:
    for raw in f:
        if "ixi-O" not in raw:
            continue

        ts_m = PAT_TS.search(raw)
        ts = ts_m.group(1) if ts_m else "00:00:00"

        # InsertESData 시간
        m = PAT_INSERT_TIME.search(raw)
        if m:
            insert_times.append((ts, float(m.group(1))))

        # sendLiveBuffer
        m = PAT_LIVE_BUFFER2.search(raw) or PAT_LIVE_BUFFER.search(raw)
        if m:
            live_buffers.append((ts, int(m.group(1)), int(m.group(2)), int(m.group(3))))

        # SendPackets
        m = PAT_SEND_PKTS.search(raw)
        if m:
            send_pkts.append((ts, int(m.group(1))))

        # ReceivePackets
        m = PAT_RECV_PKTS.search(raw) or PAT_RECV_PKTS2.search(raw)
        if m:
            total, valid = int(m.group(1)), int(m.group(2))
            recv_pkts.append((ts, total, valid))

        # sendReport
        m = PAT_SEND_REPORT.search(raw)
        if m:
            send_reports.append((ts, int(m.group(1)), int(m.group(2))))

        # CAPTURE result
        m = PAT_CAPTURE_ERR.search(raw)
        if m:
            capture_results[m.group(1)] += 1

        # RENDER errors
        m = PAT_RENDER_ERR.search(raw)
        if m:
            render_errors.append((ts, raw.strip()[-100:]))

        # micHealthCheck
        m = PAT_MIC_HEALTH.search(raw)
        if m:
            mic_health.append((ts, int(m.group(1))))

print(f"  InsertESData 샘플: {len(insert_times):,}개")
print(f"  sendLiveBuffer 샘플: {len(live_buffers)}개")
print(f"  SendPackets 샘플: {len(send_pkts)}개")
print(f"  ReceivePackets 샘플: {len(recv_pkts)}개")
print(f"  sendReport 샘플: {len(send_reports)}개")
print(f"  micHealthCheck 샘플: {len(mic_health)}개")
print()

# ──────────────────────────────────────────────
# 분석 1: InsertESData 처리 시간 이상치
# ──────────────────────────────────────────────

print("=" * 60)
print("■ 분석 1: 마이크→엔진 버퍼 처리 시간 (TX InsertESData)")
print("=" * 60)
if len(insert_times) > 10:
    vals = [t for _, t in insert_times]
    avg = statistics.mean(vals)
    stdev = statistics.stdev(vals)
    median = statistics.median(vals)
    max_t = max(vals)
    threshold = avg + 3 * stdev
    anomalies = [(ts, t) for ts, t in insert_times if t > threshold]

    print(f"  평균: {avg:.3f}ms | 중앙값: {median:.3f}ms | 표준편차: {stdev:.3f}ms")
    print(f"  최대: {max_t:.3f}ms | 이상치 기준(avg+3σ): {threshold:.3f}ms")
    print(f"  이상치 발생: {len(anomalies)}건 / {len(vals)}건 ({len(anomalies)/len(vals)*100:.2f}%)")
    if anomalies:
        print(f"\n  ⚠ 이상치 발생 시각 (상위 20건):")
        for ts, t in sorted(anomalies, key=lambda x: -x[1])[:20]:
            print(f"    [{ts}]  {t:.3f}ms  {'←← 심각' if t > threshold*2 else ''}")
    print()
    print("  → 해석: 이 지연이 20ms(1프레임) 이상 지속되면 음단절 발생 가능")
else:
    print("  데이터 부족")
print()

# ──────────────────────────────────────────────
# 분석 2: sendLiveBuffer tx_count 증가율 갭
# ──────────────────────────────────────────────

print("=" * 60)
print("■ 분석 2: 전송 패킷 카운트 갭 (sendLiveBuffer tx_count)")
print("=" * 60)
if len(live_buffers) >= 2:
    print(f"  {'시각':<20} {'tx_count':>10} {'Δtx':>8} {'rx_count':>10} {'Δrx':>8} {'elapsed':>10} {'판정'}")
    print("  " + "-" * 75)

    prev_tx, prev_rx = None, None
    gaps = []
    for ts, tx, rx, elapsed in live_buffers:
        if prev_tx is not None:
            dtx = tx - prev_tx
            drx = rx - prev_rx
            # elapsed ms 당 예상 패킷: AMR-WB = 20ms 프레임 → 3000ms/20ms = 150 packets
            expected = elapsed / 20  # 대략적 예상 패킷 수
            pct_tx = dtx / expected * 100 if expected > 0 else 0
            pct_rx = drx / expected * 100 if expected > 0 else 0
            warn = ""
            if pct_tx < 80:
                warn = f"⚠ TX {pct_tx:.0f}% (음단절 의심)"
                gaps.append((ts, dtx, drx, elapsed, pct_tx))
            elif pct_rx < 80:
                warn = f"⚠ RX {pct_rx:.0f}% (수신 손실)"
            print(f"  {ts:<20} {tx:>10} {dtx:>8} {rx:>10} {drx:>8} {elapsed:>10}ms {warn}")
        else:
            print(f"  {ts:<20} {tx:>10} {'':>8} {rx:>10} {'':>8} {elapsed:>10}ms (기준점)")
        prev_tx, prev_rx = tx, rx

    print()
    if gaps:
        print(f"  ⚠ TX 갭 발생 구간: {len(gaps)}건")
        for ts, dtx, drx, elapsed, pct in gaps:
            print(f"    [{ts}] TX {pct:.0f}% ({dtx}pkts / 예상 {elapsed/20:.0f}pkts)")
    else:
        print("  ✅ TX 갭 없음: 전송 패킷 카운트 정상 증가")
else:
    print("  데이터 부족")
print()

# ──────────────────────────────────────────────
# 분석 3: ReceivePackets 손실률
# ──────────────────────────────────────────────

print("=" * 60)
print("■ 분석 3: 수신 패킷 손실률 (ReceivePackets)")
print("=" * 60)
if len(recv_pkts) >= 2:
    for ts, total, valid in recv_pkts:
        loss = total - valid
        loss_pct = loss / total * 100 if total > 0 else 0
        warn = f"⚠ 손실 {loss_pct:.1f}%" if loss_pct > 1 else "✅"
        print(f"  [{ts}] total={total} valid={valid} loss={loss} ({loss_pct:.2f}%)  {warn}")
else:
    print("  데이터 부족")
print()

# ──────────────────────────────────────────────
# 분석 4: sendReport packetCount 증가율
# ──────────────────────────────────────────────

print("=" * 60)
print("■ 분석 4: sendReport 누적 전송 패킷 증가율")
print("=" * 60)
if len(send_reports) >= 2:
    prev_pkt = None
    for ts, pkt, octet in send_reports:
        if prev_pkt is not None:
            dpkt = pkt - prev_pkt
            avg_size = (octet / pkt) if pkt > 0 else 0
            warn = "⚠ 갭 의심" if dpkt < 30 else "✅"
            print(f"  [{ts}] packetCount={pkt} (Δ{dpkt:+}) avg_size={avg_size:.0f}bytes  {warn}")
        else:
            print(f"  [{ts}] packetCount={pkt} (기준)")
        prev_pkt = pkt
else:
    print("  데이터 부족")
print()

# ──────────────────────────────────────────────
# 분석 5: micHealthCheck buffer_count
# ──────────────────────────────────────────────

print("=" * 60)
print("■ 분석 5: 마이크 버퍼 상태 (micHealthCheck buffer_count)")
print("=" * 60)
if len(mic_health) >= 2:
    counts = [c for _, c in mic_health]
    avg_bc = statistics.mean(counts)
    print(f"  평균 buffer_count: {avg_bc:.1f}")
    for ts, c in mic_health:
        warn = ""
        if c == 0:
            warn = "⚠ buffer_count=0 (마이크 입력 없음!)"
        elif c < avg_bc * 0.5:
            warn = f"⚠ buffer_count 급감 ({c} < avg {avg_bc:.1f}의 50%)"
        print(f"  [{ts}] buffer_count={c}  {warn}")
else:
    print("  데이터 부족")
print()

# ──────────────────────────────────────────────
# 분석 6: CAPTURE 결과 집계
# ──────────────────────────────────────────────

print("=" * 60)
print("■ 분석 6: CAPTURE InsertESData 결과 집계")
print("=" * 60)
if capture_results:
    total_cap = sum(capture_results.values())
    for k, v in sorted(capture_results.items()):
        pct = v / total_cap * 100
        warn = " ⚠" if k != "OK" else ""
        print(f"  {k}: {v:,}건 ({pct:.2f}%){warn}")
else:
    print("  데이터 없음")
print()

# ──────────────────────────────────────────────
# 결론 요약
# ──────────────────────────────────────────────

print("=" * 60)
print("■ 결론: 로그 기반 음단절 감지 가능성 평가")
print("=" * 60)

has_insert = len(insert_times) > 0
has_buffer = len(live_buffers) >= 2
has_pkts   = len(recv_pkts) >= 1

print(f"""
[감지 가능한 지표]                          [실제 감지됨?]
─────────────────────────────────────────────────────────
① TX InsertESData 처리 시간 이상치           {'✅ 가능' if has_insert else '❌ 데이터 없음'}
   (20ms 프레임 기준 초과 여부)

② sendLiveBuffer tx_count 갭                {'✅ 가능' if has_buffer else '❌ 데이터 없음'}
   (3초 간격 카운트가 예상치 대비 80% 미만)

③ ReceivePackets 손실률                     {'✅ 가능' if has_pkts else '❌ 데이터 없음'}
   (totalCount vs validCount 차이)

④ micHealthCheck buffer_count=0            {'✅ 가능' if len(mic_health) > 0 else '❌ 데이터 없음'}
   (마이크 버퍼 완전 비어있음)

⑤ CAPTURE InsertESData FAIL/SKIP           {'⚠ 발생: ' + str(capture_results.get('FAIL',0)+capture_results.get('SKIP',0)) + '건' if capture_results.get('FAIL',0)+capture_results.get('SKIP',0) > 0 else '✅ 발생 없음'}

[한계]
─────────────────────────────────────────────────────────
• sendLiveBuffer는 3초 주기 → 첫 2~3글자 수준의 짧은 음단절은
  카운트 갭이 3초 평균에 희석되어 감지 어려움
• 정확한 음단절 시각(ms 단위)은 로그로 특정 불가
• InsertESData 타이밍 이상치가 가장 정밀한 지표지만
  ixi-O 앱이 ENGINE_LOG DEVEL을 노출하는 경우에만 확인 가능

[권장 테스트 자동화 방향]
─────────────────────────────────────────────────────────
→ "안녕하세요~" 음단절 감지:
  1. InsertESData 이상치 발생 여부 + 시각 기록
  2. sendLiveBuffer tx_count 갭 모니터링
  3. 수신단 Android STT 결과에서 "안녕" 누락 감지 (크로스 검증)
""")
