"""
play_test_tone.py
──────────────────────────────────────────────────────────────────────────────
1kHz 사인파 테스트 톤을 USB 오디오 출력 장치로 재생합니다.

macOS 재열거(index drift) 대응:
  - device 미지정 → USB 출력 중 첫 번째 자동 선택 (시스템 기본 금지)
  - device 지정 → 비USB이면 ioreg 기반으로 가장 가까운 USB 인덱스로 복구
  - USB 장치 없음 → 오류 종료 (맥북 내장 스피커 재생 차단)

사용법:
    python play_test_tone.py [--device INDEX]

옵션:
    --device  sounddevice 출력 장치 index (생략 시 USB 첫 번째 자동 선택)
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import argparse
import sys

import numpy as np
import sounddevice as sd

from usb_audio_devices import get_usb_audio_product_names, get_usb_audio_output_indices


def play_test_tone(device: int | None, output_pair: tuple[int, int] | None = None) -> None:
    devs = sd.query_devices()
    usb_names = get_usb_audio_product_names()
    usb_indices = get_usb_audio_output_indices()

    # ── 장치 미지정 → USB 첫 번째 자동 선택 ──────────────────────────────────
    if device is None:
        if not usb_indices:
            print('❌ USB 오디오 출력 장치가 연결되어 있지 않습니다.', flush=True)
            sys.exit(1)
        device = usb_indices[0]
        print(
            f'ℹ️ 장치 미지정 → USB 출력 자동: device={device} \'{devs[device]["name"]}\'',
            flush=True,
        )

    # ── USB 여부 검증 + 자동 복구 ────────────────────────────────────────────
    # HDMI 등 연결 시 인덱스가 밀릴 수 있으므로, 비USB 장치라면
    # 해당 위치의 USB 장치를 자동으로 찾아 복구한다.
    dev_name: str = devs[device]['name']
    is_usb = dev_name in usb_names or 'USB Audio' in dev_name

    if not is_usb:
        if not usb_indices:
            print(
                f'❌ device={device} \'{dev_name}\'은(는) USB 장치가 아니며, '
                f'연결된 USB 오디오 장치도 없습니다.',
                flush=True,
            )
            sys.exit(1)
        # 인덱스 드리프트 복구: 원래 device 값에 가장 가까운 USB 인덱스 선택
        old_device = device
        # usb_indices 중 원래 인덱스보다 크거나 같은 첫 번째, 없으면 마지막
        candidates = [i for i in usb_indices if i >= old_device]
        device = candidates[0] if candidates else usb_indices[-1]
        dev_name = devs[device]['name']
        print(
            f'⚠️ device={old_device} 은(는) USB 장치가 아님 (HDMI 등으로 인덱스 변경됨)\n'
            f'   → USB 장치로 자동 복구: device={device} \'{dev_name}\'',
            flush=True,
        )

    # ── 출력 채널 확인 ────────────────────────────────────────────────────────
    info = devs[device]
    if info['max_output_channels'] == 0:
        print(f'⚠️ device={device} \'{dev_name}\' 는 출력 채널 없음', flush=True)
        sys.exit(1)

    # ── 1kHz 사인파 1초 생성 및 재생 ─────────────────────────────────────────
    sr = int(info['default_samplerate'])
    dur = 1.0
    t = np.linspace(0, dur, int(sr * dur), endpoint=False)
    tone = (np.sin(2 * np.pi * 1000 * t) * 0.6).astype('float32')
    stereo = np.stack([tone, tone], axis=1)

    # ── output_pair 지정 시 멀티채널 매핑 ────────────────────────────────────
    if output_pair is not None:
        target_max = max(output_pair) + 1
        dev_max_out = int(info.get('max_output_channels', 2))
        if target_max > dev_max_out:
            print(f'⚠️ output_pair={output_pair} 가 장치 최대 채널({dev_max_out}) 초과 → (0,1)로 폴백', flush=True)
            output_pair = (0, 1)
            target_max = 2
        total_out_ch = max(target_max, dev_max_out)
        mapped = np.zeros((len(stereo), total_out_ch), dtype='float32')
        mapped[:, output_pair[0]] = stereo[:, 0]
        mapped[:, output_pair[1]] = stereo[:, 1]
        stereo = mapped
        print(f'🎛 멀티채널 출력: output_pair={output_pair}, total_ch={total_out_ch}', flush=True)

    out_channels = stereo.shape[1]
    print(f'🔔 테스트 톤 → device={device} \'{dev_name}\' sr={sr}Hz ch={out_channels}', flush=True)
    sd.play(stereo, samplerate=sr, device=device, blocking=True)
    print('✅ 재생 완료', flush=True)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description='1kHz 테스트 톤을 USB 오디오 장치로 재생')
    p.add_argument(
        '--device', type=int, default=None,
        help='sounddevice 출력 장치 index (생략 시 USB 첫 번째 자동 선택)',
    )
    p.add_argument(
        '--output-pair', type=str, default=None,
        help='CONNECT 6 출력 채널 쌍 (예: "6,7"=Mobile Out). 생략 시 0,1(Out 1/2).',
    )
    return p.parse_args()


if __name__ == '__main__':
    try:
        args = _parse_args()
        op = None
        if args.output_pair:
            parts = args.output_pair.split(',')
            op = (int(parts[0]), int(parts[1]))
        play_test_tone(args.device, output_pair=op)
    except Exception as e:
        print(f'❌ 실패: {e}', flush=True)
        sys.exit(1)
