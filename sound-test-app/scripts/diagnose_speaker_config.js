/**
 * 📋 Speaker Config 진단 스크립트
 *
 * 사용법: 브라우저 DevTools 콘솔에 복사/붙여넣기 후 Enter
 * (Tauri 앱에서 Cmd+Shift+I 로 DevTools 열기)
 *
 * 진단 항목:
 *  1. localStorage에 저장된 글로벌 speaker 값
 *  2. TC별 오버라이드 값
 *  3. 현재 연결된 디바이스 목록 (Tauri invoke)
 *  4. 중복/stale/빈값 검출
 *  5. TC 실행 시 실제로 사용될 디바이스 예측
 */
(async function diagnoseSpeakerConfig() {
  const SEP = "═".repeat(60);
  const sep = "─".repeat(60);
  console.log(SEP);
  console.log("🔍 Speaker Config 진단 시작");
  console.log(SEP);

  // ── 1. localStorage: 글로벌 speaker ──
  const raw = localStorage.getItem("speakerConfig_v1");
  const global = raw ? JSON.parse(raw) : {};
  const s1 = global.speaker1Device || "(비어있음)";
  const s2 = global.speaker2Device || "(비어있음)";
  console.log("\n📦 localStorage [speakerConfig_v1]:");
  console.log(`  speaker1Device = ${s1}`);
  console.log(`  speaker2Device = ${s2}`);
  console.log(`  speaker1Number = ${global.speaker1Number || "(비어있음)"}`);
  console.log(`  speaker2Number = ${global.speaker2Number || "(비어있음)"}`);

  // 플랫폼 판별
  const isAndroid = (v) => typeof v === 'string' && v.includes(":");
  console.log(`  speaker1 플랫폼: ${isAndroid(s1) ? "Android" : "iOS"}`);
  console.log(`  speaker2 플랫폼: ${isAndroid(s2) ? "Android" : "iOS"}`);

  // ── 2. localStorage: TC별 오버라이드 ──
  const tcRaw = localStorage.getItem("ixio-tc-speaker-config");
  const tcConfig = tcRaw ? JSON.parse(tcRaw) : {};
  console.log(`\n📦 localStorage [ixio-tc-speaker-config]:`);
  if (Object.keys(tcConfig).length === 0) {
    console.log("  (비어있음 - TC별 오버라이드 없음)");
  } else {
    for (const [tcId, entry] of Object.entries(tcConfig)) {
      const e = entry;
      if (e.speaker1Device || e.speaker2Device) {
        console.log(`  ${tcId}: speaker1=${e.speaker1Device || "(빈)"}, speaker2=${e.speaker2Device || "(빈)"}, profile=${e.profileId || "(빈)"}`);
      } else {
        console.log(`  ${tcId}: (오버라이드 없음, profileId=${e.profileId || "(빈)"})`);
      }
    }
  }

  // ── 3. 연결된 디바이스 목록 ──
  console.log(`\n${sep}`);
  console.log("📱 연결된 디바이스 목록 조회 중...");
  let androidDevices = [];
  let iosDevices = [];
  try {
    const { invoke } = window.__TAURI_INTERNALS__ || await import("@tauri-apps/api/core");
    const androidResult = await invoke("list_android_devices");
    androidDevices = androidResult?.devices || [];
    console.log(`  Android: ${androidDevices.length}개`);
    androidDevices.forEach(d => console.log(`    ✅ ${d.udid} (${d.name})`));
  } catch (e) {
    console.log(`  ❌ Android 목록 조회 실패: ${e}`);
  }
  try {
    const { invoke } = window.__TAURI_INTERNALS__ || await import("@tauri-apps/api/core");
    const iosResult = await invoke("list_ios_devices");
    iosDevices = iosResult?.devices || [];
    console.log(`  iOS: ${iosDevices.length}개`);
    iosDevices.forEach(d => console.log(`    ✅ ${d.udid} (${d.name})`));
  } catch (e) {
    console.log(`  ❌ iOS 목록 조회 실패: ${e}`);
  }

  const allDevices = [...androidDevices, ...iosDevices];
  const connectedUdids = new Set(allDevices.map(d => d.udid));

  // ── 4. 문제 진단 ──
  console.log(`\n${sep}`);
  console.log("🔎 문제 진단:");
  let problems = 0;

  // 4-1. 글로벌 speaker 중복
  if (s1 === s2 && s1 !== "(비어있음)") {
    problems++;
    console.log(`  🔴 [P${problems}] 글로벌 중복: speaker1 === speaker2 === ${s1}`);
    console.log(`      → 두 화자가 동일 디바이스를 가리키고 있어 한쪽은 반드시 연결 실패합니다.`);
  }

  // 4-2. 글로벌 speaker stale (연결 안 됨)
  if (s1 !== "(비어있음)" && !connectedUdids.has(s1)) {
    problems++;
    console.log(`  🔴 [P${problems}] speaker1 stale: ${s1} (현재 연결된 디바이스에 없음)`);
  }
  if (s2 !== "(비어있음)" && !connectedUdids.has(s2)) {
    problems++;
    console.log(`  🔴 [P${problems}] speaker2 stale: ${s2} (현재 연결된 디바이스에 없음)`);
  }

  // 4-3. 글로벌 speaker 비어있음 + 디바이스 있음
  if (s1 === "(비어있음)" && allDevices.length > 0) {
    problems++;
    console.log(`  🟡 [P${problems}] speaker1 비어있음 (디바이스 ${allDevices.length}개 가용)`);
  }
  if (s2 === "(비어있음)" && allDevices.length > 1) {
    problems++;
    console.log(`  🟡 [P${problems}] speaker2 비어있음 (디바이스 ${allDevices.length}개 가용)`);
  }

  // 4-4. 양쪽 같은 플랫폼
  if (s1 !== "(비어있음)" && s2 !== "(비어있음)" && isAndroid(s1) === isAndroid(s2)) {
    problems++;
    const platform = isAndroid(s1) ? "Android" : "iOS";
    console.log(`  🟡 [P${problems}] 양쪽 모두 ${platform}: 보통 Android+iOS 1대씩 사용`);
  }

  // 4-5. TC 오버라이드 중복/stale
  for (const [tcId, entry] of Object.entries(tcConfig)) {
    const e = entry;
    if (e.speaker1Device && e.speaker2Device && e.speaker1Device === e.speaker2Device) {
      problems++;
      console.log(`  🔴 [P${problems}] ${tcId} TC 오버라이드 중복: 양쪽 ${e.speaker1Device}`);
    }
    if (e.speaker1Device && !connectedUdids.has(e.speaker1Device)) {
      problems++;
      console.log(`  🔴 [P${problems}] ${tcId} speaker1 stale: ${e.speaker1Device}`);
    }
    if (e.speaker2Device && !connectedUdids.has(e.speaker2Device)) {
      problems++;
      console.log(`  🔴 [P${problems}] ${tcId} speaker2 stale: ${e.speaker2Device}`);
    }
  }

  if (problems === 0) {
    console.log("  ✅ 문제 없음");
  }

  // ── 5. TC_02 실행 시뮬레이션 ──
  console.log(`\n${sep}`);
  console.log("🎯 TC_02 실행 시뮬레이션:");

  const tc02Entry = tcConfig["TC_02"];
  const hasTcOverride = !!(tc02Entry?.speaker1Device && tc02Entry?.speaker2Device);
  console.log(`  TC별 오버라이드: ${hasTcOverride ? "있음" : "없음"}`);

  let finalS1, finalS2;
  if (hasTcOverride) {
    finalS1 = tc02Entry.speaker1Device;
    finalS2 = tc02Entry.speaker2Device;
    console.log(`  → TC 오버라이드 사용: s1=${finalS1}, s2=${finalS2}`);
  } else {
    // TC_02는 역방향 → 글로벌 스왑
    finalS1 = global.speaker2Device || "";
    finalS2 = global.speaker1Device || "";
    console.log(`  → 글로벌 역방향 스왑: s1=${finalS1}, s2=${finalS2}`);
  }
  console.log(`  최종 화자1 디바이스: ${finalS1} (${isAndroid(finalS1) ? "Android" : "iOS"})`);
  console.log(`  최종 화자2 디바이스: ${finalS2} (${isAndroid(finalS2) ? "Android" : "iOS"})`);
  if (finalS1 === finalS2) {
    console.log(`  🔴 최종 결과도 중복! 이게 바로 양쪽 같은 디바이스로 테스트가 실행되는 원인입니다.`);
  }

  // ── 6. 올바른 값 제안 ──
  console.log(`\n${sep}`);
  console.log("💡 올바른 설정 제안:");
  const android = androidDevices[0];
  const ios = iosDevices[0];
  if (android && ios) {
    console.log(`  speaker1 (발신) = ${android.udid} (Android: ${android.name})`);
    console.log(`  speaker2 (수신) = ${ios.udid} (iOS: ${ios.name})`);
    console.log(`\n  🔧 수동 수정 명령 (아래를 콘솔에 붙여넣기):`);
    console.log(`  ───`);
    const fixGlobal = `(() => { const c = JSON.parse(localStorage.getItem("speakerConfig_v1") || "{}"); c.speaker1Device = "${android.udid}"; c.speaker2Device = "${ios.udid}"; localStorage.setItem("speakerConfig_v1", JSON.stringify(c)); const tc = JSON.parse(localStorage.getItem("ixio-tc-speaker-config") || "{}"); for (const e of Object.values(tc)) { e.speaker1Device = ""; e.speaker2Device = ""; } localStorage.setItem("ixio-tc-speaker-config", JSON.stringify(tc)); console.log("✅ 수정 완료! 페이지를 새로고침하세요."); })()`;
    console.log(`  ${fixGlobal}`);
  } else {
    console.log(`  ⚠️ Android와 iOS 디바이스가 모두 연결되어야 합니다.`);
    console.log(`     현재: Android ${androidDevices.length}개, iOS ${iosDevices.length}개`);
  }

  console.log(`\n${SEP}`);
  console.log("🔍 진단 완료");
  console.log(SEP);
})();
