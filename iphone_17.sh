#!/bin/bash
# iPhone 17 Pro WDA 기동 스크립트
# UDID: 00008150-00110C341E38401C
# Bundle: com.jjun.1 / Team: 35597M53Y5

UDID="00008150-00110C341E38401C"
XCTESTRUN=~/Library/Developer/Xcode/DerivedData/WebDriverAgent-avbeqkqvwykfxbbzghazymezllin/Build/Products/WebDriverAgentRunner_iphoneos26.2-arm64.xctestrun
WDA_LOG="/tmp/wda_17pro.log"

# 기존 WDA 프로세스 종료
xcrun devicectl device process terminate \
  --device "$UDID" \
  com.jjun.1.WebDriverAgentRunner.xctrunner 2>/dev/null || true

sleep 1

xcodebuild test-without-building \
  -xctestrun "$XCTESTRUN" \
  -destination "id=$UDID" \
  > "$WDA_LOG" 2>&1 &

echo "WDA 기동 중... (로그: $WDA_LOG)"

for i in $(seq 1 30); do
  sleep 2
  url=$(grep -o "ServerURLHere->http://[^<]*" "$WDA_LOG" 2>/dev/null | head -1 | sed 's/ServerURLHere->//')
  if [[ -n "$url" ]]; then
    echo "✅ WDA URL: $url"
    curl -s --max-time 3 "${url}/status" | python3 -c \
      "import sys,json; d=json.load(sys.stdin); print('ready=', d.get('value',{}).get('ready'))" 2>/dev/null
    break
  fi
  grep -q "error:" "$WDA_LOG" 2>/dev/null && { echo "❌ 에러:"; grep "error:" "$WDA_LOG" | tail -3; exit 1; }
  echo "⏳ ${i}..."
done
