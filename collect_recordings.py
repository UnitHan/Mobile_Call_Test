#!/usr/bin/env python3
"""
collect_recordings.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
통화 종료 후 Android / iOS 에서 녹음 파일을 자동 수집하여

  1. recordings/ 폴더에 타임스탬프+OS명으로 저장
       recording_iOS_YYYYMMDD_HHMMSS_N.wav
       recording_android_YYYYMMDD_HHMMSS_N.wav

  2. m4a → wav 변환 (ffmpeg, 16kHz mono)

  3. analyze_hybrid.py 실행 → HTML 보고서 생성

사용:
  python collect_recordings.py              # 최신 1개씩 수집 후 분석
  python collect_recordings.py --count 2   # 최신 2개씩
  python collect_recordings.py --no-analyze # 수집만, 분석 제외
  python collect_recordings.py --count 1 --no-analyze
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os, sys, re, json, subprocess, shutil, tempfile, argparse
from datetime import datetime
from pathlib import Path

# ─────────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────────
BASE_DIR        = Path(__file__).parent
RECORDINGS_DIR  = BASE_DIR / "recordings"
ANALYZE_SCRIPT  = BASE_DIR / "analyze_hybrid.py"
PYTHON          = str(BASE_DIR / ".venv" / "bin" / "python")

# Android 통화녹음 경로 (ixiO 앱)
ANDROID_REC_DIR = "/sdcard/Recordings/ixiO"

# iOS 앱 번들 ID
IOS_BUNDLE_ID   = "com.lguplus.aicallagent"

# 스크립트 기반 음단절 분석 — 정답지 WAV
REF_WAV         = BASE_DIR / "audiomass-output_mono.wav"

# ─────────────────────────────────────────────────
# 파일명 패턴
# ─────────────────────────────────────────────────

# iOS:   UUID20260305091754119mvoip..._0.m4a
#        UUID = 36 chars with dashes
_IOS_PAT = re.compile(
    r'^[A-Fa-f0-9]{8}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{12}'
    r'(\d{8})(\d{6})\d+mvoip.*\.m4a$',
    re.IGNORECASE
)

# Android: NAME_OR_NUMBER_YYYYMMDDHHMMSSMMM.m4a  (타임스탬프가 마지막 _-segment)
_ANDROID_PAT = re.compile(r'.*_(\d{8})(\d{6})\d+\.m4a$', re.IGNORECASE)


def ts_key(date8: str, time6: str) -> str:
    """YYYYMMDD + HHMMSS → 정렬용 키 'YYYYMMDDHHMMSS'"""
    return date8 + time6


# ─────────────────────────────────────────────────
# 장치 탐지
# ─────────────────────────────────────────────────

def detect_android() -> str | None:
    """adb devices 에서 연결된 첫 번째 장치 serial 반환"""
    try:
        out = subprocess.check_output(
            ["adb", "devices"], stderr=subprocess.DEVNULL, text=True
        )
    except FileNotFoundError:
        return None

    for line in out.splitlines()[1:]:
        line = line.strip()
        if line and "\tdevice" in line:
            serial = line.split("\t")[0].strip()
            print(f"  [Android] {serial}")
            return serial
    return None


def detect_ios() -> str | None:
    """xcrun devicectl 에서 connected 상태인 첫 번째 장치 UDID 반환"""
    try:
        out = subprocess.check_output(
            ["xcrun", "devicectl", "list", "devices"],
            stderr=subprocess.DEVNULL, text=True
        )
    except FileNotFoundError:
        return None

    # 헤더/구분선/unavailable 제외
    for line in out.splitlines():
        if not line.strip() or line.startswith("Name") or line.startswith("---"):
            continue
        if "unavailable" in line.lower():
            continue
        # UDID 패턴: 8-4-4-4-12 hex
        m = re.search(
            r'([A-Fa-f0-9]{8}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{12})',
            line
        )
        if m and "connected" in line.lower():
            udid = m.group(1)
            # 장치 이름 추출 (줄 맨 앞)
            name = line.split()[0]
            print(f"  [iOS]     {name} ({udid})")
            return udid
    return None


# ─────────────────────────────────────────────────
# 녹음 목록 조회
# ─────────────────────────────────────────────────

def list_android_recordings(serial: str) -> list[tuple[str, str]]:
    """
    Android 장치에서 /sdcard/Recordings/ixiO/ 내 .m4a 목록 조회
    반환: [(ts_key 'YYYYMMDDHHMMSS', 파일명), ...] – 타임스탬프 오름차순
    """
    try:
        out = subprocess.check_output(
            ["adb", "-s", serial, "shell", "ls", ANDROID_REC_DIR],
            stderr=subprocess.DEVNULL, text=True
        )
    except subprocess.CalledProcessError:
        return []

    results = []
    for fname in out.splitlines():
        fname = fname.strip()
        m = _ANDROID_PAT.match(fname)
        if m:
            results.append((ts_key(m.group(1), m.group(2)), fname))

    results.sort(key=lambda x: x[0])
    return results


def list_ios_recordings(udid: str) -> list[tuple[str, str]]:
    """
    iOS 장치 앱 컨테이너에서 Documents/*.m4a 목록 조회 (JSON 출력 파싱)
    반환: [(ts_key 'YYYYMMDDHHMMSS', 파일명), ...] – 타임스탬프 오름차순
    """
    json_tmp = Path(tempfile.mktemp(suffix=".json"))
    try:
        subprocess.run(
            [
                "xcrun", "devicectl", "device", "info", "files",
                "--device", udid,
                "--domain-type", "appDataContainer",
                "--domain-identifier", IOS_BUNDLE_ID,
                "--json-output", str(json_tmp),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True
        )
    except subprocess.CalledProcessError:
        return []

    if not json_tmp.exists():
        return []

    try:
        data = json.loads(json_tmp.read_text())
    except json.JSONDecodeError:
        return []
    finally:
        json_tmp.unlink(missing_ok=True)

    results = []
    # JSON 구조: data["result"]["files"] = [{"name": "Documents/...", ...}, ...]
    files = []
    if isinstance(data, dict):
        result = data.get("result", data)
        files  = result.get("files", result.get("entries", []))

    for entry in files:
        name = entry.get("name", "") if isinstance(entry, dict) else str(entry)
        # "Documents/UUID20260305091754119mvoip..._0.m4a"  형태
        fname = Path(name).name
        m = _IOS_PAT.match(fname)
        if m:
            results.append((ts_key(m.group(1), m.group(2)), fname))

    results.sort(key=lambda x: x[0])
    return results


# ─────────────────────────────────────────────────
# 파일 다운로드
# ─────────────────────────────────────────────────

def pull_android(serial: str, fname: str, dst: Path) -> bool:
    """adb pull 로 단일 파일 다운로드"""
    src = f"{ANDROID_REC_DIR}/{fname}"
    try:
        subprocess.run(
            ["adb", "-s", serial, "pull", src, str(dst)],
            check=True, stderr=subprocess.DEVNULL
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"    [오류] adb pull 실패: {e}")
        return False


def pull_ios(udid: str, fname: str, dst: Path) -> bool:
    """xcrun devicectl device copy from 으로 단일 파일 다운로드"""
    source = f"Documents/{fname}"
    try:
        subprocess.run(
            [
                "xcrun", "devicectl", "device", "copy", "from",
                "--device", udid,
                "--domain-type", "appDataContainer",
                "--domain-identifier", IOS_BUNDLE_ID,
                "--source", source,
                "--destination", str(dst),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"    [오류] devicectl copy 실패: {e.stderr.decode(errors='ignore').strip()}")
        return False


# ─────────────────────────────────────────────────
# 변환: m4a → wav
# ─────────────────────────────────────────────────

def convert_to_wav(src: Path, dst: Path) -> bool:
    """ffmpeg 로 m4a → wav (16kHz, 모노)"""
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(src),
                "-ar", "16000",
                "-ac", "1",
                "-acodec", "pcm_s16le",
                str(dst),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        print(f"    [오류] ffmpeg 변환 실패: {src.name}")
        return False


# ─────────────────────────────────────────────────
# 스크립트 기반 음단절 분석
# ─────────────────────────────────────────────────

def run_script_analysis(wav_path: Path) -> None:
    """script_gap_detector를 이용해 대본 기반 음단절 분석 실행"""
    if not REF_WAV.exists():
        print(f"  [경고] 정답지 WAV 없음: {REF_WAV.name} — 스크립트 분석 생략")
        return

    try:
        from script_gap_detector import (  # type: ignore
            analyze_by_script,
            load_script_reference,
            print_report,
        )
    except ImportError:
        print("  [경고] script_gap_detector 모듈을 찾을 수 없습니다 — 스크립트 분석 생략")
        return

    script = load_script_reference()
    if not script:
        print("  [경고] SCRIPT_REFERENCE 로드 실패 — 스크립트 분석 생략")
        return

    print(f"  파일: {wav_path.name}  /  정답지: {REF_WAV.name}")
    result = analyze_by_script(
        ref_path=str(REF_WAV),
        test_path=str(wav_path),
        script_text=script,
        silence_gap_ms=700,
        min_seg_ms=400,
        corr_threshold=0.30,
        search_sec=8.0,
    )
    print_report(result)


# ─────────────────────────────────────────────────
# 메인 파이프라인
# ─────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Android/iOS 통화녹음 수집 → WAV 변환 → 분석"
    )
    parser.add_argument(
        "--count", "-n", type=int, default=1,
        help="각 기기에서 가져올 최신 녹음 수 (기본: 1)"
    )
    parser.add_argument(
        "--no-analyze", action="store_true",
        help="분석(analyze_hybrid.py) 실행 생략"
    )
    args = parser.parse_args()
    count = args.count

    print("=" * 60)
    print("  통화녹음 수집 파이프라인")
    print("=" * 60)

    # ── 1. 장치 탐지 ──────────────────────────────
    print("\n[1/4] 장치 탐지 중...")
    android_serial = detect_android()
    ios_udid       = detect_ios()

    if not android_serial and not ios_udid:
        print("  [오류] 연결된 장치가 없습니다. adb / xcrun 확인 바랍니다.")
        sys.exit(1)

    if not android_serial:
        print("  [경고] Android 장치 없음 — iOS만 수집합니다.")
    if not ios_udid:
        print("  [경고] iOS 장치 없음 — Android만 수집합니다.")

    # ── 2. 녹음 목록 조회 ────────────────────────
    print(f"\n[2/4] 최신 {count}개 녹음 조회 중...")

    android_files: list[tuple[str, str]] = []
    ios_files:     list[tuple[str, str]] = []

    if android_serial:
        all_and = list_android_recordings(android_serial)
        android_files = all_and[-count:]
        print(f"  Android: {len(all_and)}개 중 최신 {len(android_files)}개 선택")
        for ts, fn in android_files:
            print(f"    {ts[:8]}_{ts[8:]} — {fn}")

    if ios_udid:
        all_ios = list_ios_recordings(ios_udid)
        ios_files = all_ios[-count:]
        print(f"  iOS:     {len(all_ios)}개 중 최신 {len(ios_files)}개 선택")
        for ts, fn in ios_files:
            print(f"    {ts[:8]}_{ts[8:]} — {fn}")

    if not android_files and not ios_files:
        print("  [오류] 수집할 녹음 파일이 없습니다.")
        sys.exit(1)

    # ── 3. 다운로드 & 변환 ───────────────────────
    print("\n[3/4] 다운로드 및 WAV 변환 중...")
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

    collected: list[dict] = []   # {idx, os, date8, time6, wav_path}

    def process_files(files, os_tag: str, pull_fn):
        for seq, (ts, fname) in enumerate(files, start=1):
            date8 = ts[:8]
            time6 = ts[8:]
            stem  = f"recording_{os_tag}_{date8}_{time6}_{seq}"
            print(f"\n  [{os_tag} #{seq}] {fname}")

            # 임시 저장 후 변환
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_m4a = Path(tmpdir) / fname
                print(f"    ↓ 다운로드...", end="", flush=True)
                ok = pull_fn(fname, tmp_m4a)
                if not ok or not tmp_m4a.exists():
                    print(" 실패")
                    continue
                print(f" {tmp_m4a.stat().st_size // 1024}KB")

                # m4a도 복사
                dst_m4a = RECORDINGS_DIR / f"{stem}.m4a"
                shutil.copy2(tmp_m4a, dst_m4a)
                print(f"    📁 {dst_m4a.name}")

                # wav 변환
                dst_wav = RECORDINGS_DIR / f"{stem}.wav"
                print(f"    🔄 WAV 변환...", end="", flush=True)
                ok = convert_to_wav(tmp_m4a, dst_wav)
                if ok:
                    print(f" {dst_wav.stat().st_size // 1024}KB")
                    print(f"    ✅ {dst_wav.name}")
                    collected.append({
                        "idx":   seq,
                        "os":    os_tag,
                        "date8": date8,
                        "time6": time6,
                        "wav":   str(dst_wav),
                    })
                else:
                    print(" 실패")

    if android_serial and android_files:
        process_files(
            android_files, "android",
            lambda fn, dst: pull_android(android_serial, fn, dst)
        )

    if ios_udid and ios_files:
        process_files(
            ios_files, "iOS",
            lambda fn, dst: pull_ios(ios_udid, fn, dst)
        )

    # 결과 요약
    print("\n" + "-" * 40)
    print(f"수집 완료: {len(collected)}개 WAV")
    for c in collected:
        print(f"  [{c['os']} #{c['idx']}] {Path(c['wav']).name}")

    if not collected:
        print("[오류] 수집된 파일 없음 — 분석을 건너뜁니다.")
        sys.exit(1)

    # ── 4. 분석 실행 ─────────────────────────────
    if args.no_analyze:
        print("\n[4/5] 분석 생략 (--no-analyze)")
        print("\n완료! recordings/ 폴더를 확인하세요.")
        return

    print("\n[4/5] analyze_hybrid.py 실행 중...")
    print("=" * 60)

    result = subprocess.run(
        [PYTHON, str(ANALYZE_SCRIPT)],
        cwd=str(BASE_DIR)
    )

    if result.returncode == 0:
        report = BASE_DIR / "hybrid_report.html"
        print("=" * 60)
        print(f"  hybrid 보고서: {report}")
    else:
        print(f"\n[오류] 분석 스크립트가 {result.returncode} 코드로 종료됐습니다.")
        sys.exit(result.returncode)

    # ── 5. 스크립트 기반 음단절 분석 ─────────────
    print("\n[5/5] 스크립트 기반 음단절 분석 중...")
    for c in collected:
        run_script_analysis(Path(c["wav"]))

    print("\n✅ 완료!")


if __name__ == "__main__":
    main()
