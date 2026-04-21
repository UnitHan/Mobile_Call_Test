#!/bin/bash
# ixi-O 통화 테스트 로그 캡처 스크립트
# Usage: bash capture_log.sh

LOG_FILE="/Users/qabulls/Documents/sound/log_new.txt"
MAX_WAIT=30  # iPhone 연결 최대 대기 시간(초)

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ixi-O 통화 로그 캡처 시작"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 1. iPhone 연결 대기
echo "📱 iPhone USB 연결 감지 중..."
UDID=""
for i in $(seq 1 $MAX_WAIT); do
    UDID=$(idevice_id -l 2>/dev/null | head -1)
    if [ -n "$UDID" ]; then
        break
    fi
    printf "\r   대기 중... %d초" "$i"
    sleep 1
done

if [ -z "$UDID" ]; then
    echo ""
    echo "❌ iPhone이 감지되지 않았습니다."
    echo "   → iPhone을 USB로 연결하고 '이 컴퓨터를 신뢰'를 탭하세요."
    exit 1
fi

echo ""
echo "✅ iPhone 감지됨: $UDID"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🎯 지금 바로 ixi-O 앱에서 통화를 걸어주세요!"
echo "   로그 파일: $LOG_FILE"
echo "   중지: Ctrl+C"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 2. 로그 캡처 시작
rm -f "$LOG_FILE"
echo "⏺  $(date '+%H:%M:%S') 캡처 시작"
idevicesyslog -u "$UDID" 2>/dev/null | tee "$LOG_FILE"

echo ""
echo "⏹  캡처 종료. 로그: $LOG_FILE"
