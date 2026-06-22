"""ESP32 CSI 프레임 기반 실내 움직임 감지."""

import time
from collections import Counter, deque

import numpy as np
import serial

from utils import csi_to_amp, parse_csi_line

SERIAL_PORT = "COM4"
BAUD_RATE = 115200
CSI_LEN = 128

WINDOW_SIZE = 20
SLIDE_INTERVAL = 0.15
STATE_HISTORY_SIZE = 12

# 적응형 배경 모델.
WARMUP_FRAMES = 60  # 약 15초.
BG_ALPHA = 0.003
BG_UPDATE_TH = 1.08

# 상승 즉시 반영, 하강 상태 유지.
SCORE_UP = 0.45
SCORE_DOWN = 0.1

# 상대 점수 임계값.
TH_SAFE = 1.6
TH_ALERT = 2.0

LABEL_MAP = {
    "SAFE":     "🟢 SAFE     | No Activity",
    "DETECTED": "🟡 DETECTED | Presence Suspected",
    "ALERT":    "🔴 ALERT    | Movement Detected",
}


def read_frame(serial_port: serial.Serial) -> tuple[int | None, np.ndarray | None]:
    """시리얼 한 줄을 RSSI와 진폭 배열로 변환."""
    line = serial_port.readline().decode(errors="ignore").strip()
    rssi, csi = parse_csi_line(line, CSI_LEN)
    if csi is None:
        return None, None
    return rssi, csi_to_amp(csi, CSI_LEN)


def compute_raw_score(amplitudes: deque[np.ndarray]) -> float:
    """서브캐리어별 시간축 표준편차의 평균 계산."""
    window = np.asarray(amplitudes)
    return float(np.std(window, axis=0).mean())


def finish_warmup(warmup_scores: list[float]) -> float:
    """워밍업 점수에서 초기 배경값 추정."""
    scores = np.asarray(warmup_scores)
    median = np.median(scores)
    clean_scores = scores[scores <= median * 1.5]
    if len(clean_scores) < 10:
        clean_scores = scores  # 표본 부족 시 전체 점수 사용.

    background_score = float(np.percentile(clean_scores, 20))
    removed_count = len(scores) - len(clean_scores)
    print(
        f"[완료] 스파이크 {removed_count}개 제거 | 초기 배경={background_score:.2f} | "
        f"SAFE<{background_score * TH_SAFE:.2f} | "
        f"ALERT>{background_score * TH_ALERT:.2f}"
    )
    return background_score


def classify(relative_score: float) -> str:
    if relative_score < TH_SAFE:
        return "SAFE"
    if relative_score > TH_ALERT:
        return "ALERT"
    return "DETECTED"


def main():
    serial_port = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.2)
    amp_buffer = deque(maxlen=WINDOW_SIZE)
    rssi_buffer = deque(maxlen=WINDOW_SIZE)
    state_history = deque(maxlen=STATE_HISTORY_SIZE)

    last_evaluation = time.monotonic()
    warmup_scores = []
    bg_score = None
    smooth_score = None

    print("=== Zone Detection Demo Started ===")
    print(f"[워밍업] 지금 방에서 나가 주세요! 빈 방 기준선을 {WARMUP_FRAMES}프레임 동안 측정합니다...")

    while True:
        rssi, amplitude = read_frame(serial_port)
        if amplitude is None:
            continue

        rssi_buffer.append(rssi)
        amp_buffer.append(amplitude)

        now = time.monotonic()
        if now - last_evaluation < SLIDE_INTERVAL:
            continue
        last_evaluation = now

        if len(amp_buffer) < WINDOW_SIZE:
            continue

        raw_score = compute_raw_score(amp_buffer)
        median_rssi = np.median(rssi_buffer)

        if bg_score is None:
            warmup_scores.append(raw_score)
            if len(warmup_scores) % 10 == 0:
                print(
                    f"[{time.strftime('%H:%M:%S')}] 워밍업 "
                    f"{len(warmup_scores)}/{WARMUP_FRAMES}  score={raw_score:.2f}"
                )
            if len(warmup_scores) >= WARMUP_FRAMES:
                bg_score = finish_warmup(warmup_scores)
                smooth_score = bg_score
            continue

        alpha = SCORE_UP if raw_score > smooth_score else SCORE_DOWN
        smooth_score = (1 - alpha) * smooth_score + alpha * raw_score

        relative_score = smooth_score / (bg_score + 1e-9)

        # 빈 공간으로 판단될 때만 배경 갱신.
        if relative_score < BG_UPDATE_TH:
            bg_score = (1 - BG_ALPHA) * bg_score + BG_ALPHA * raw_score

        state_history.append(classify(relative_score))
        final_state = Counter(state_history).most_common(1)[0][0]

        print(
            f"[{time.strftime('%H:%M:%S')}] "
            f"{LABEL_MAP[final_state]} | "
            f"RSSI={median_rssi:.1f} | "
            f"score={raw_score:.2f} rel={relative_score:.2f} bg={bg_score:.2f}"
        )


if __name__ == "__main__":
    main()
