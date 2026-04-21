#!/bin/bash
# tunneld LaunchDaemon 수정 및 재시작 스크립트
# 실행: sudo bash fix_tunneld.sh

if [ "$EUID" -ne 0 ]; then
    echo "sudo로 실행해주세요: sudo bash fix_tunneld.sh"
    exit 1
fi

PLIST="/Library/LaunchDaemons/com.qabulls.pymobiledevice3.tunneld.plist"

echo "1) tunneld 중지 중..."
launchctl unload "$PLIST" 2>/dev/null || true

echo "2) plist 경로 수정 (venv → .venv)..."
sed -i '' 's|/venv/bin/pymobiledevice3|/.venv/bin/pymobiledevice3|g' "$PLIST"

echo "3) 수정된 plist 확인:"
grep pymobiledevice3 "$PLIST"

echo "4) tunneld 재시작..."
launchctl load "$PLIST"

echo "5) 10초 대기..."
sleep 10

echo "6) 상태 확인:"
launchctl list | grep tunneld
cat /tmp/pymobiledevice3-tunneld.log 2>/dev/null | tail -5
cat /tmp/pymobiledevice3-tunneld-error.log 2>/dev/null | tail -5

echo ""
echo "완료! 이제 아래 명령으로 로그 캡처할 수 있습니다:"
echo "  cd /Users/qabulls/Documents/sound"
echo "  source .venv/bin/activate"
echo "  idevicesyslog -u 00008150-00110C341E38401C -n > log_new.txt"
