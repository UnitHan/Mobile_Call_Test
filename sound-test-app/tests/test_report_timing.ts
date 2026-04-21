/**
 * MOS 보고서 생성 시 tcResultsRef 타이밍 문제 재현 테스트
 *
 * 테스트 대상:
 *   useTcRunner.ts의 반복 루프 → 보고서 생성 → tcResultsRef.current 읽기
 *
 * 재현 시나리오:
 *   10회 반복 TC_00 → 마지막 회차가 RUNNING으로 보고서에 포함
 */

// ── 최소한의 타입 정의 ──

interface TcResult {
  runId: string;
  tcId: string;
  status: string;
  repeatIndex: number | null;
  iosVisqolMos: number | null;
  androidVisqolMos: number | null;
  voipDelayMs: number | null;
  startedAt: string;
  durationMs: number;
}

// ── React useState/useRef 시뮬레이션 ──

let tcResults: TcResult[] = [];
let tcResultsRef = { current: tcResults };
const pendingUpdaters: Array<(prev: TcResult[]) => TcResult[]> = [];

function setTcResults(updater: (prev: TcResult[]) => TcResult[]) {
  // React의 동작 시뮬레이션: updater는 큐에 쌓이고, 렌더링 시 배치 처리
  pendingUpdaters.push(updater);
}

/** React 렌더링 시뮬레이션: 큐에 쌓인 업데이터를 순서대로 적용 */
function flushReactUpdates() {
  let state = tcResults;
  while (pendingUpdaters.length > 0) {
    const updater = pendingUpdaters.shift()!;
    state = updater(state);
  }
  tcResults = state;
  // 렌더링 시점에 ref 갱신 (원본 코드: tcResultsRef.current = tcResults)
  tcResultsRef.current = tcResults;
}

// ── useTcRunner의 핵심 로직 시뮬레이션 ──

function upsertResult_ORIGINAL(patch: Partial<TcResult> & { runId: string }) {
  setTcResults((prev) => {
    const idx = prev.findIndex((r) => r.runId === patch.runId);
    if (idx === -1) return prev;
    const next = [...prev];
    next[idx] = { ...prev[idx], ...patch };
    return next;
  });
}

function upsertResult_WITH_REF_FIX(patch: Partial<TcResult> & { runId: string }) {
  setTcResults((prev) => {
    const idx = prev.findIndex((r) => r.runId === patch.runId);
    if (idx === -1) return prev;
    const next = [...prev];
    next[idx] = { ...prev[idx], ...patch };
    // 패치된 수정: ref도 즉시 갱신
    tcResultsRef.current = next;
    return next;
  });
}

function addPlaceholder(runId: string, tcId: string, repeatIndex: number) {
  const placeholder: TcResult = {
    runId,
    tcId,
    status: "RUNNING",
    repeatIndex,
    iosVisqolMos: null,
    androidVisqolMos: null,
    voipDelayMs: null,
    startedAt: new Date().toISOString(),
    durationMs: 0,
  };
  setTcResults((prev) => {
    if (prev.some((r) => r.runId === runId)) return prev;
    return [placeholder, ...prev];
  });
}

/** runSingleTc 시뮬레이션: placeholder 추가 → await 분석 → finalResult upsert */
async function simulateRunSingleTc(
  tcId: string,
  repeatIndex: number,
  upsertFn: typeof upsertResult_ORIGINAL,
): Promise<TcResult> {
  const runId = `run-${repeatIndex}`;

  // 1. placeholder 추가 (RUNNING)
  addPlaceholder(runId, tcId, repeatIndex);

  // 2. React 렌더링 사이클 시뮬레이션 — await가 마이크로태스크를 양보
  await new Promise((r) => setTimeout(r, 1));
  flushReactUpdates();

  // 3. 테스트 실행 시뮬레이션 (invoke → Python → 결과)
  await new Promise((r) => setTimeout(r, 5));

  // 4. 분석 완료 → finalResult
  const finalResult: TcResult = {
    runId,
    tcId,
    status: "PASS",
    repeatIndex,
    iosVisqolMos: 3.5 + Math.random() * 1.0,
    androidVisqolMos: 4.0 + Math.random() * 0.5,
    voipDelayMs: 350 + Math.floor(Math.random() * 100),
    startedAt: new Date().toISOString(),
    durationMs: 65000,
  };

  upsertFn(finalResult);
  return finalResult;
}

/** 보고서 생성 시뮬레이션: tcResultsRef.current를 읽어서 데이터 수집 */
function simulateReportGeneration(runIds: string[]): {
  runs: Array<{ repeat_index: number | null; status: string; ios_visqol_mos: number | null }>;
  runningCount: number;
  totalCount: number;
} {
  const currentResults = tcResultsRef.current;
  const sessionRuns = currentResults
    .filter((r) => runIds.includes(r.runId) && r.tcId === "TC_00")
    .map((r) => ({
      repeat_index: r.repeatIndex,
      ios_visqol_mos: r.iosVisqolMos,
      android_visqol_mos: r.androidVisqolMos,
      voip_delay_ms: r.voipDelayMs,
      started_at: r.startedAt,
      duration_ms: r.durationMs,
      status: r.status,
    }));

  const runningCount = sessionRuns.filter((r) => r.status === "RUNNING").length;
  return { runs: sessionRuns, runningCount, totalCount: sessionRuns.length };
}

// ── 테스트 실행 ──

async function test_original_code() {
  console.log("=== 테스트 1: 원본 코드 (ref 갱신 없음) ===");
  tcResults = [];
  tcResultsRef = { current: tcResults };
  pendingUpdaters.length = 0;

  const runIds: string[] = [];
  const total = 10;

  for (let i = 1; i <= total; i++) {
    const result = await simulateRunSingleTc("TC_00", i, upsertResult_ORIGINAL);
    runIds.push(result.runId);

    // 회차 간 3초 대기 시뮬레이션 (렌더링 기회)
    if (i < total) {
      await new Promise((r) => setTimeout(r, 1));
      flushReactUpdates();
    }
  }

  // 반복 루프 직후 → 보고서 생성 (렌더링 전)
  const report = simulateReportGeneration(runIds);
  console.log(`  보고서 총 ${report.totalCount}건, RUNNING ${report.runningCount}건`);

  for (const r of report.runs) {
    if (r.status === "RUNNING") {
      console.log(`  ❌ 회차 ${r.repeat_index}: status=${r.status}, mos=${r.ios_visqol_mos}`);
    }
  }

  if (report.runningCount > 0) {
    console.log(`  >> 결과: ❌ FAIL — ${report.runningCount}건이 RUNNING 상태로 보고서에 포함됨`);
  } else {
    console.log(`  >> 결과: ✅ PASS — 모든 건이 최종 상태`);
  }

  // 렌더링 후에는?
  flushReactUpdates();
  const reportAfterRender = simulateReportGeneration(runIds);
  console.log(`  (렌더링 후) 총 ${reportAfterRender.totalCount}건, RUNNING ${reportAfterRender.runningCount}건`);
  console.log();
}

async function test_ref_fix() {
  console.log("=== 테스트 2: ref 즉시 갱신 수정 ===");
  tcResults = [];
  tcResultsRef = { current: tcResults };
  pendingUpdaters.length = 0;

  const runIds: string[] = [];
  const total = 10;

  for (let i = 1; i <= total; i++) {
    const result = await simulateRunSingleTc("TC_00", i, upsertResult_WITH_REF_FIX);
    runIds.push(result.runId);

    if (i < total) {
      await new Promise((r) => setTimeout(r, 1));
      flushReactUpdates();
    }
  }

  const report = simulateReportGeneration(runIds);
  console.log(`  보고서 총 ${report.totalCount}건, RUNNING ${report.runningCount}건`);

  for (const r of report.runs) {
    if (r.status === "RUNNING") {
      console.log(`  ❌ 회차 ${r.repeat_index}: status=${r.status}, mos=${r.ios_visqol_mos}`);
    }
  }

  if (report.runningCount > 0) {
    console.log(`  >> 결과: ❌ FAIL — ${report.runningCount}건이 RUNNING 상태로 보고서에 포함됨`);
  } else {
    console.log(`  >> 결과: ✅ PASS — 모든 건이 최종 상태`);
  }
  console.log();
}

async function test_batch_updater_problem() {
  console.log("=== 테스트 3: 배치 업데이터 누적 문제 분석 ===");
  tcResults = [];
  tcResultsRef = { current: tcResults };
  pendingUpdaters.length = 0;

  // 10회차까지 실행하되, setTcResults 호출 순서를 추적
  const callLog: string[] = [];

  const origSetTcResults = setTcResults;
  const trackedSetTcResults = (updater: (prev: TcResult[]) => TcResult[]) => {
    const wrappedUpdater = (prev: TcResult[]) => {
      const result = updater(prev);
      const changed = result !== prev;
      const addedCount = result.length - prev.length;
      const runningCount = result.filter(r => r.status === "RUNNING").length;
      const passCount = result.filter(r => r.status === "PASS").length;
      callLog.push(`  [updater] prev=${prev.length} → next=${result.length} (added=${addedCount}) RUNNING=${runningCount} PASS=${passCount}`);
      return result;
    };
    pendingUpdaters.push(wrappedUpdater);
  };

  // 마지막 회차 시뮬레이션 (10회차)
  const runId = "run-10";

  // 1. placeholder 추가
  const placeholder: TcResult = {
    runId, tcId: "TC_00", status: "RUNNING", repeatIndex: 10,
    iosVisqolMos: null, androidVisqolMos: null, voipDelayMs: null,
    startedAt: new Date().toISOString(), durationMs: 0,
  };
  trackedSetTcResults((prev) => {
    if (prev.some((r) => r.runId === runId)) return prev;
    return [placeholder, ...prev];
  });

  console.log(`  pendingUpdaters 큐: ${pendingUpdaters.length}개 (placeholder 추가 후)`);

  // 2. React 렌더링은 아직 안 일어남 → 마지막 회차의 await에서는 렌더링 기회 없음
  //    (마지막 회차에서는 sleep(3000) 호출 안 함)

  // 3. finalResult upsert
  const finalResult: TcResult = {
    runId, tcId: "TC_00", status: "PASS", repeatIndex: 10,
    iosVisqolMos: 4.05, androidVisqolMos: 4.37, voipDelayMs: 403,
    startedAt: new Date().toISOString(), durationMs: 65000,
  };
  trackedSetTcResults((prev) => {
    const idx = prev.findIndex((r) => r.runId === runId);
    if (idx === -1) {
      callLog.push(`  [upsert] ⚠️ runId ${runId} NOT FOUND in prev (length=${prev.length})`);
      return prev;
    }
    const next = [...prev];
    next[idx] = { ...prev[idx], ...finalResult };
    // ref fix 적용
    tcResultsRef.current = next;
    return next;
  });

  console.log(`  pendingUpdaters 큐: ${pendingUpdaters.length}개 (upsert 후)`);

  // 4. React 배치 처리 시뮬레이션
  console.log("  --- flushReactUpdates 시작 ---");
  let state = tcResults;
  while (pendingUpdaters.length > 0) {
    const updater = pendingUpdaters.shift()!;
    state = updater(state);
  }
  tcResults = state;
  console.log("  --- flushReactUpdates 완료 ---");

  for (const log of callLog) {
    console.log(log);
  }

  // 5. ref 상태 확인
  const refState = tcResultsRef.current;
  console.log(`\n  tcResultsRef.current: ${refState.length}건`);
  for (const r of refState) {
    console.log(`    ${r.runId}: status=${r.status}, mos=${r.iosVisqolMos}`);
  }
  console.log();
}

async function test_real_scenario_10runs() {
  console.log("=== 테스트 4: 실제 10회 반복 시나리오 (React 배치 타이밍 정밀 시뮬레이션) ===");
  tcResults = [];
  tcResultsRef = { current: tcResults };
  pendingUpdaters.length = 0;

  const runIds: string[] = [];
  const total = 10;

  for (let i = 1; i <= total; i++) {
    const runId = `run-${i}`;

    // --- runSingleTc 시작 ---

    // 1. placeholder (RUNNING)
    const placeholder: TcResult = {
      runId, tcId: "TC_00", status: "RUNNING", repeatIndex: i,
      iosVisqolMos: null, androidVisqolMos: null, voipDelayMs: null,
      startedAt: new Date().toISOString(), durationMs: 0,
    };
    setTcResults((prev) => {
      if (prev.some((r) => r.runId === runId)) return prev;
      return [placeholder, ...prev];
    });

    // 2. invoke("run_ixio_test") → await으로 마이크로태스크 양보
    //    React는 이 사이에 렌더링 가능 (실제 React에서는 보장되지 않음)
    await new Promise((r) => setTimeout(r, 1));
    // 마지막 회차가 아니면 이전 회차들의 업데이터가 이미 flush됨
    // 하지만 현재 회차의 placeholder도 이 시점에 flush될 수 있음
    flushReactUpdates();

    // 3. 분석 완료 → upsert
    const finalResult: TcResult = {
      runId, tcId: "TC_00", status: "PASS", repeatIndex: i,
      iosVisqolMos: 3.5 + Math.random(), androidVisqolMos: 4.0 + Math.random() * 0.5,
      voipDelayMs: 350 + Math.floor(Math.random() * 100),
      startedAt: new Date().toISOString(), durationMs: 65000,
    };
    upsertResult_WITH_REF_FIX(finalResult);
    runIds.push(runId);

    // --- runSingleTc 종료 ---

    // 마지막 회차: sleep(3000) 호출 안 함 → 렌더링 기회 없음
    if (i < total) {
      await new Promise((r) => setTimeout(r, 1));
      flushReactUpdates();
    }
    // 마지막 회차에서는 flushReactUpdates가 호출 안 됨!
  }

  // 반복 루프 직후 → 보고서 생성
  console.log(`  [보고서 생성 시점] tcResultsRef.current 상태:`);
  const refState = tcResultsRef.current;
  let runningCount = 0;
  for (const r of refState) {
    if (r.status === "RUNNING") {
      console.log(`    ❌ ${r.runId}: RUNNING (mos=${r.iosVisqolMos})`);
      runningCount++;
    }
  }
  if (runningCount === 0) {
    console.log(`    ✅ 모든 ${refState.length}건이 최종 상태`);
  } else {
    console.log(`    >> ${runningCount}건이 RUNNING — 이것이 보고서에 포함됨`);
  }

  // 실제 보고서 생성 시뮬레이션
  const report = simulateReportGeneration(runIds);
  console.log(`\n  보고서: 총 ${report.totalCount}건, RUNNING ${report.runningCount}건`);
  if (report.runningCount > 0) {
    console.log(`  >> ❌ 버그 재현됨!`);
  } else {
    console.log(`  >> ✅ 버그 없음`);
  }
  console.log();
}

async function test_where_placeholder_goes() {
  console.log("=== 테스트 5: placeholder가 addPlaceholder와 upsert 사이에 flush 안 되는 케이스 ===");
  tcResults = [];
  tcResultsRef = { current: tcResults };
  pendingUpdaters.length = 0;

  // 9회차까지 정상 flush된 상태 시뮬레이션
  for (let i = 1; i <= 9; i++) {
    tcResults.push({
      runId: `run-${i}`, tcId: "TC_00", status: "PASS", repeatIndex: i,
      iosVisqolMos: 4.0, androidVisqolMos: 4.3, voipDelayMs: 400,
      startedAt: new Date().toISOString(), durationMs: 65000,
    });
  }
  tcResultsRef.current = tcResults;

  // 10회차: placeholder 추가
  const runId = "run-10";
  const placeholder: TcResult = {
    runId, tcId: "TC_00", status: "RUNNING", repeatIndex: 10,
    iosVisqolMos: null, androidVisqolMos: null, voipDelayMs: null,
    startedAt: new Date().toISOString(), durationMs: 0,
  };
  setTcResults((prev) => {
    if (prev.some((r) => r.runId === runId)) return prev;
    return [placeholder, ...prev];
  });

  console.log(`  큐 상태: ${pendingUpdaters.length}개 업데이터 대기 중`);
  console.log(`  tcResultsRef.current: ${tcResultsRef.current.length}건 (9건 — placeholder 아직 없음)`);

  // ⚡ 핵심: placeholder가 flush되기 전에 upsert가 실행됨
  // 실제 코드에서는 invoke("run_ixio_test")의 await 사이에 React 렌더링이
  // 반드시 발생하는 것은 아님!

  // 시나리오 A: flush 없이 바로 upsert
  console.log("\n  --- 시나리오 A: flush 없이 upsert ---");
  const finalResult: TcResult = {
    runId, tcId: "TC_00", status: "PASS", repeatIndex: 10,
    iosVisqolMos: 4.05, androidVisqolMos: 4.37, voipDelayMs: 403,
    startedAt: new Date().toISOString(), durationMs: 65000,
  };

  // upsert_WITH_REF_FIX
  setTcResults((prev) => {
    const idx = prev.findIndex((r) => r.runId === runId);
    console.log(`    [upsert updater] prev.length=${prev.length}, findIndex(${runId})=${idx}`);
    if (idx === -1) {
      console.log(`    ⚠️ runId NOT FOUND — upsert 무시됨!`);
      return prev;
    }
    const next = [...prev];
    next[idx] = { ...prev[idx], ...finalResult };
    tcResultsRef.current = next;
    return next;
  });

  console.log(`  큐: ${pendingUpdaters.length}개 대기 중`);

  // React 배치 처리
  console.log("\n  --- React flush ---");
  let state = tcResults;
  let step = 0;
  while (pendingUpdaters.length > 0) {
    const updater = pendingUpdaters.shift()!;
    const prev = state;
    state = updater(prev);
    step++;
    console.log(`    step ${step}: ${prev.length} → ${state.length} (RUNNING=${state.filter(r => r.status === "RUNNING").length})`);
  }
  tcResults = state;

  console.log(`\n  최종 tcResultsRef.current:`);
  for (const r of tcResultsRef.current) {
    if (r.runId === "run-10") {
      console.log(`    ${r.runId}: status=${r.status}, mos=${r.iosVisqolMos}`);
    }
  }

  const run10 = tcResultsRef.current.find(r => r.runId === "run-10");
  if (run10?.status === "PASS") {
    console.log(`  >> ✅ 10회차 정상`);
  } else {
    console.log(`  >> ❌ 10회차 여전히 ${run10?.status}`);
  }
  console.log();
}

async function test_concurrent_setstate_race() {
  console.log("=== 테스트 6: setTcResults 업데이터 체이닝에서 ref 갱신 위치 문제 ===");
  tcResults = [];
  tcResultsRef = { current: tcResults };
  pendingUpdaters.length = 0;

  // 핵심 문제 재현:
  // setTcResults의 업데이터가 2개 큐에 쌓임:
  //   1. addPlaceholder: prev=[] → [placeholder(RUNNING)]
  //   2. upsertResult:  prev=[placeholder(RUNNING)] → [finalResult(PASS)]
  //
  // React가 배치 처리할 때 업데이터는 체이닝됨 (prev → next → next...)
  // "WITH_REF_FIX"에서 tcResultsRef.current = next 를 upsert 업데이터 안에서 하면
  // step 2에서 ref가 [finalResult(PASS)]로 갱신됨 ✅
  //
  // 하지만! addPlaceholder의 setTcResults가 먼저 실행되면서
  // step 1에서 tcResultsRef.current = [placeholder(RUNNING)]으로 갱신하지 않음
  // → step 2에서 prev는 step 1의 결과인 [placeholder] 를 받음 → findIndex 성공 → OK

  // 그러면 왜 실패하지?
  // 답: React에서는 setTcResults updater가 **두 번** 호출될 수 있음 (StrictMode)
  // 또는, setTcResults가 이전 렌더링의 state를 기반으로 호출될 수 있음

  // 실제 React 동작을 더 정확히 시뮬레이션
  // React 18 batching: 모든 async 컨텍스트에서 상태 업데이트가 자동 배치됨
  // await 후에 flush되는 것이 아니라, 다음 마이크로태스크에서 flush

  const runId = "run-10";

  // placeholder 추가
  setTcResults((prev) => {
    if (prev.some((r) => r.runId === runId)) return prev;
    const p: TcResult = {
      runId, tcId: "TC_00", status: "RUNNING", repeatIndex: 10,
      iosVisqolMos: null, androidVisqolMos: null, voipDelayMs: null,
      startedAt: "", durationMs: 0,
    };
    return [p, ...prev];
  });

  // ⚡ 문제 시나리오: placeholder setTcResults와 upsert setTcResults가
  // 같은 배치에 들어가는 경우 vs 다른 배치에 들어가는 경우

  // Case A: 같은 배치 (flush 전에 둘 다 큐잉)
  console.log("  Case A: 같은 배치에 들어가는 경우");
  setTcResults((prev) => {
    const idx = prev.findIndex((r) => r.runId === runId);
    if (idx === -1) {
      console.log(`    ⚠️ Case A: findIndex FAILED (prev.length=${prev.length})`);
      return prev;
    }
    const next = [...prev];
    next[idx] = { ...prev[idx], status: "PASS", iosVisqolMos: 4.05 };
    tcResultsRef.current = next;
    console.log(`    ✅ Case A: findIndex=${idx}, status=PASS`);
    return next;
  });

  // flush 
  let state = tcResults; // []
  while (pendingUpdaters.length > 0) {
    const updater = pendingUpdaters.shift()!;
    state = updater(state);
  }
  tcResults = state;

  const run10a = tcResultsRef.current.find(r => r.runId === "run-10");
  console.log(`  Case A 결과: status=${run10a?.status} → ${run10a?.status === "PASS" ? "✅" : "❌"}`);

  // Case B: 다른 배치 — placeholder만 먼저 flush, 그 다음 upsert
  console.log("\n  Case B: placeholder만 먼저 flush, upsert는 다음 배치");
  tcResults = [];
  tcResultsRef = { current: tcResults };
  pendingUpdaters.length = 0;

  setTcResults((prev) => {
    if (prev.some((r) => r.runId === runId)) return prev;
    const p: TcResult = {
      runId, tcId: "TC_00", status: "RUNNING", repeatIndex: 10,
      iosVisqolMos: null, androidVisqolMos: null, voipDelayMs: null,
      startedAt: "", durationMs: 0,
    };
    return [p, ...prev];
  });

  // 첫 번째 배치 flush
  state = tcResults;
  while (pendingUpdaters.length > 0) {
    state = pendingUpdaters.shift()!(state);
  }
  tcResults = state;
  tcResultsRef.current = tcResults; // 렌더링

  console.log(`  placeholder flush 후: tcResults.length=${tcResults.length}, status=${tcResults[0]?.status}`);

  // 두 번째 배치: upsert
  setTcResults((prev) => {
    const idx = prev.findIndex((r) => r.runId === runId);
    if (idx === -1) {
      console.log(`    ⚠️ Case B: findIndex FAILED`);
      return prev;
    }
    const next = [...prev];
    next[idx] = { ...prev[idx], status: "PASS", iosVisqolMos: 4.05 };
    tcResultsRef.current = next;
    console.log(`    ✅ Case B: findIndex=${idx}, status=PASS`);
    return next;
  });

  // 두 번째 배치 flush
  state = tcResults;
  while (pendingUpdaters.length > 0) {
    state = pendingUpdaters.shift()!(state);
  }
  tcResults = state;

  const run10b = tcResultsRef.current.find(r => r.runId === "run-10");
  console.log(`  Case B 결과: status=${run10b?.status} → ${run10b?.status === "PASS" ? "✅" : "❌"}`);

  // Case C: 이전 회차 렌더링 결과와 충돌 (tcResultsRef.current = tcResults 경쟁)
  console.log("\n  Case C: tcResultsRef.current = tcResults 렌더링이 ref fix를 덮어쓰는 경우");
  tcResults = [];
  tcResultsRef = { current: tcResults };
  pendingUpdaters.length = 0;

  // 9회차까지 완료된 상태
  for (let i = 1; i <= 9; i++) {
    tcResults.push({
      runId: `run-${i}`, tcId: "TC_00", status: "PASS", repeatIndex: i,
      iosVisqolMos: 4.0, androidVisqolMos: 4.3, voipDelayMs: 400,
      startedAt: "", durationMs: 65000,
    });
  }
  tcResultsRef.current = tcResults;

  // 10회차 placeholder + upsert가 같은 배치
  setTcResults((prev) => {
    const p: TcResult = {
      runId: "run-10", tcId: "TC_00", status: "RUNNING", repeatIndex: 10,
      iosVisqolMos: null, androidVisqolMos: null, voipDelayMs: null,
      startedAt: "", durationMs: 0,
    };
    return [p, ...prev];
  });

  setTcResults((prev) => {
    const idx = prev.findIndex((r) => r.runId === "run-10");
    if (idx === -1) return prev;
    const next = [...prev];
    next[idx] = { ...prev[idx], status: "PASS", iosVisqolMos: 4.05 };
    tcResultsRef.current = next;
    return next;
  });

  // 배치 flush → ref는 [PASS, ...9개PASS] 로 설정됨 
  state = tcResults;
  while (pendingUpdaters.length > 0) {
    state = pendingUpdaters.shift()!(state);
  }
  tcResults = state;

  // 그런데! React 렌더링에서 `tcResultsRef.current = tcResults` 가 다시 실행됨
  // 이 코드가 문제의 핵심일 수 있음!
  // 만약 렌더링 과정에서 이전 상태가 ref에 덮어보면?

  // 시뮬레이션: 렌더링 직전의 상태로 ref 덮어쓰기
  // (실제 React: setTcResults → 렌더링 → 컴포넌트 본문 재실행 → tcResultsRef.current = tcResults)
  // 하지만 tcResults는 이미 flush된 최신 상태이므로 이 경우는 문제 없음

  const run10c = tcResultsRef.current.find(r => r.runId === "run-10");
  console.log(`  Case C 결과: status=${run10c?.status} → ${run10c?.status === "PASS" ? "✅" : "❌"}`);
  console.log();
}

async function test_the_real_bug() {
  console.log("=== 테스트 7: 실제 버그 — 마지막 회차 placeholder가 flush 안 된 상태에서 보고서 생성 ===");
  console.log("  (ref fix가 적용된 상태에서도 실패하는 시나리오)\n");

  tcResults = [];
  tcResultsRef = { current: tcResults };
  pendingUpdaters.length = 0;

  const runIds: string[] = [];

  // 1~9회차는 정상: 각 회차의 placeholder가 flush된 후 upsert
  for (let i = 1; i <= 9; i++) {
    const runId = `run-${i}`;
    // placeholder 추가
    setTcResults((prev) => {
      const p: TcResult = {
        runId, tcId: "TC_00", status: "RUNNING", repeatIndex: i,
        iosVisqolMos: null, androidVisqolMos: null, voipDelayMs: null,
        startedAt: "", durationMs: 0,
      };
      return [p, ...prev];
    });

    // invoke 반환 → flush 기회
    flushReactUpdates();

    // upsert
    upsertResult_WITH_REF_FIX({
      runId, tcId: "TC_00", status: "PASS", repeatIndex: i,
      iosVisqolMos: 4.0, androidVisqolMos: 4.3, voipDelayMs: 400,
      startedAt: "", durationMs: 65000,
    } as TcResult);

    // sleep(3000) → flush 기회
    flushReactUpdates();
    runIds.push(runId);
  }

  console.log(`  9회차까지 완료: tcResultsRef.current.length=${tcResultsRef.current.length}`);
  console.log(`  RUNNING=${tcResultsRef.current.filter(r => r.status === "RUNNING").length}`);

  // --- 10회차 (마지막) ---
  const runId = "run-10";

  // placeholder
  setTcResults((prev) => {
    const p: TcResult = {
      runId, tcId: "TC_00", status: "RUNNING", repeatIndex: 10,
      iosVisqolMos: null, androidVisqolMos: null, voipDelayMs: null,
      startedAt: "", durationMs: 0,
    };
    return [p, ...prev];
  });

  console.log(`\n  10회차 placeholder 큐잉됨 (pendingUpdaters=${pendingUpdaters.length})`);

  // invoke 반환 → flush 기회 (React에서는 await 후 배치 flush)
  flushReactUpdates();
  console.log(`  invoke 후 flush: tcResultsRef.current.length=${tcResultsRef.current.length}`);

  // upsert (WITH REF FIX)
  upsertResult_WITH_REF_FIX({
    runId, tcId: "TC_00", status: "PASS", repeatIndex: 10,
    iosVisqolMos: 4.05, androidVisqolMos: 4.37, voipDelayMs: 403,
    startedAt: "", durationMs: 65000,
  } as TcResult);

  console.log(`  upsert 큐잉됨 (pendingUpdaters=${pendingUpdaters.length})`);

  // ⚡ 마지막 회차에서는 sleep(3000) 호출 안 함 → flush 기회 없음!
  // 하지만 ref fix가 적용되었으므로 setTcResults 업데이터 안에서 ref 갱신됨
  // 문제: 업데이터가 아직 큐에 있으면 실행 안 됨!

  runIds.push(runId);

  console.log(`  flush 전 tcResultsRef.current에서 run-10 상태:`);
  const run10before = tcResultsRef.current.find(r => r.runId === "run-10");
  console.log(`    ${run10before ? `status=${run10before.status}` : "NOT FOUND"}`);

  // 보고서 생성
  const report = simulateReportGeneration(runIds);
  console.log(`\n  보고서 생성 결과: 총 ${report.totalCount}건, RUNNING ${report.runningCount}건`);

  if (report.runningCount > 0) {
    for (const r of report.runs) {
      if (r.status === "RUNNING") {
        console.log(`    ❌ 회차 ${r.repeat_index}: RUNNING (mos=${r.ios_visqol_mos})`);
      }
    }
    console.log("\n  >> ❌❌❌ 버그 재현됨! ref fix만으로는 부족함!");
    console.log("  >> 원인: upsert의 setTcResults 업데이터가 아직 큐에 있어 실행되지 않음");
    console.log("  >> ref fix는 업데이터 '실행 시' 갱신하지만, 업데이터 자체가 미실행 상태");
  } else {
    console.log("  >> ✅ 버그 없음 (ref fix가 효과 있음)");
  }

  // flush 후 확인
  flushReactUpdates();
  const run10after = tcResultsRef.current.find(r => r.runId === "run-10");
  console.log(`\n  flush 후 run-10: status=${run10after?.status}`);
  console.log();
}

// ── 실행 ──
async function test_final_fix_runResultsMap() {
  console.log("=== 테스트 8: 최종 수정 — runResultsMap으로 반환값 직접 수집 ===");
  console.log("  (tcResultsRef.current 대신 runSingleTc 반환값 사용)\n");

  tcResults = [];
  tcResultsRef = { current: tcResults };
  pendingUpdaters.length = 0;

  const runIds: string[] = [];
  const runResultsMap = new Map<string, TcResult>();  // ← 핵심 수정
  const total = 10;

  for (let i = 1; i <= total; i++) {
    const runId = `run-${i}`;

    // placeholder (RUNNING) — React state에 추가
    setTcResults((prev) => {
      const p: TcResult = {
        runId, tcId: "TC_00", status: "RUNNING", repeatIndex: i,
        iosVisqolMos: null, androidVisqolMos: null, voipDelayMs: null,
        startedAt: new Date().toISOString(), durationMs: 0,
      };
      return [p, ...prev];
    });

    // invoke 반환 대기 시뮬레이션
    await new Promise((r) => setTimeout(r, 1));
    flushReactUpdates();

    // 분석 완료 → finalResult
    const finalResult: TcResult = {
      runId, tcId: "TC_00", status: "PASS", repeatIndex: i,
      iosVisqolMos: 3.5 + Math.random(), androidVisqolMos: 4.0 + Math.random() * 0.5,
      voipDelayMs: 350 + Math.floor(Math.random() * 100),
      startedAt: new Date().toISOString(), durationMs: 65000,
    };

    // upsert → React state (비동기 배치)
    upsertResult_WITH_REF_FIX(finalResult);

    // ★ 반환값을 직접 Map에 수집 (React 상태 무관)
    runIds.push(runId);
    runResultsMap.set(runId, finalResult);

    // 마지막 회차에서는 sleep/flush 없음
    if (i < total) {
      await new Promise((r) => setTimeout(r, 1));
      flushReactUpdates();
    }
  }

  // ── 보고서 생성: runResultsMap 사용 (tcResultsRef.current 사용 안 함) ──
  const collectedResults = runIds
    .map((id) => runResultsMap.get(id))
    .filter((r): r is TcResult => r != null);

  const sessionRuns = collectedResults
    .filter((r) => r.tcId === "TC_00")
    .map((r) => ({
      repeat_index: r.repeatIndex,
      ios_visqol_mos: r.iosVisqolMos,
      android_visqol_mos: r.androidVisqolMos,
      voip_delay_ms: r.voipDelayMs,
      started_at: r.startedAt,
      duration_ms: r.durationMs,
      status: r.status,
    }));

  const runningCount = sessionRuns.filter((r) => r.status === "RUNNING").length;
  console.log(`  보고서: 총 ${sessionRuns.length}건, RUNNING ${runningCount}건`);

  if (runningCount > 0) {
    for (const r of sessionRuns) {
      if (r.status === "RUNNING") {
        console.log(`    ❌ 회차 ${r.repeat_index}: RUNNING`);
      }
    }
    console.log("  >> ❌ 여전히 실패");
  } else {
    console.log("  >> ✅✅✅ 모든 10건이 최종 상태 (PASS) — runResultsMap 방식 정상 동작!");
  }

  // 비교: tcResultsRef.current는 여전히 stale한지 확인
  const refRunning = tcResultsRef.current.filter(r => r.status === "RUNNING").length;
  console.log(`\n  [참고] tcResultsRef.current의 RUNNING 수: ${refRunning} (flush 전이므로 stale)`);
  flushReactUpdates();
  const refRunningAfter = tcResultsRef.current.filter(r => r.status === "RUNNING").length;
  console.log(`  [참고] flush 후 tcResultsRef.current의 RUNNING 수: ${refRunningAfter}`);
  console.log();
}

async function runAllTests() {
  await test_original_code();
  await test_ref_fix();
  await test_batch_updater_problem();
  await test_real_scenario_10runs();
  await test_where_placeholder_goes();
  await test_concurrent_setstate_race();
  await test_the_real_bug();
  await test_final_fix_runResultsMap();

  console.log("========================================");
  console.log("결론 요약:");
  console.log("  ref fix (tcResultsRef.current = next)는 업데이터 '실행 시점'에만 동작.");
  console.log("  마지막 회차의 upsert setTcResults 업데이터가 큐에 남아");
  console.log("  보고서 생성 시점에 아직 실행되지 않으면 ref에는 이전 상태가 남아있음.");
  console.log("  → 해결책: runResultsMap으로 runSingleTc 반환값을 직접 수집 ✅");
}

runAllTests().catch(console.error);
