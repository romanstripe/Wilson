# detect_zone.py
import serial
import numpy as np
import time
from collections import deque, Counter
from utils import parse_csi_line, csi_to_amp

SERIAL_PORT    = "COM4"
BAUD_RATE      = 115200
CSI_LEN        = 128
WINDOW_SIZE    = 20       # 윈도우 크기
SLIDE_INTERVAL = 0.15     # 빠른 갱신

# ── 적응형 배경 모델 파라미터 ─────────────────────────────────────────
WARMUP_FRAMES  = 60       # 초기 배경 추정 프레임 수 (~15초)
BG_ALPHA       = 0.003    # 배경 EMA 속도 (느리게 — 사람 있을 때 적응 최소화)
BG_UPDATE_TH   = 1.08     # 배경은 이 비율 이하에서만 업데이트 (사람 있으면 고정)

# 비대칭 EMA: 올라갈 땐 빠르게, 내려갈 땐 느리게
SCORE_UP       = 0.45     # 상승 속도 (움직임 즉시 반영)
SCORE_DOWN     = 0.1     # 하강 속도 (ALERT/DETECTED 상태 오래 유지)

# 상대 점수(현재/배경) 임계값
TH_SAFE        = 1.6     # 이하 → SAFE  (더 민감)
TH_ALERT       = 2.0     # 이상 → ALERT

ser           = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.2)
amp_buffer    = deque(maxlen=WINDOW_SIZE)
rssi_buffer   = deque(maxlen=WINDOW_SIZE)
state_history = deque(maxlen=12)  # 더 긴 상태 기억 → 빠른 복귀 방지
last_eval     = time.time()

warmup_scores  = []
bg_score       = None     # None이어야 워밍업 진입
smooth_score   = None

LABEL_MAP = {
    "SAFE":     "🟢 SAFE     | No Activity",
    "DETECTED": "🟡 DETECTED | Presence Suspected",
    "ALERT":    "🔴 ALERT    | Movement Detected",
}

print("=== Zone Detection Demo Started ===")
print(f"[워밍업] ⚠️  지금 방에서 나가 주세요! 빈 방 기준선을 {WARMUP_FRAMES}프레임 동안 측정합니다...")

while True:
    line = ser.readline().decode(errors="ignore").strip()
    rssi, csi = parse_csi_line(line, CSI_LEN)
    if csi is None:
        continue

    amp = csi_to_amp(csi, CSI_LEN)
    rssi_buffer.append(rssi)
    amp_buffer.append(amp)

    now = time.time()
    if now - last_eval < SLIDE_INTERVAL:
        continue
    last_eval = now

    if len(amp_buffer) < WINDOW_SIZE:
        continue

    w         = np.array(amp_buffer)           # (WINDOW_SIZE, 64)
    raw_score = np.mean(np.std(w, axis=0))     # 서브캐리어별 시간축 std 평균
    rssi_med  = np.median(rssi_buffer)

    # ── 워밍업: 초기 배경값 추정 ──────────────────────────────────────
    if bg_score is None:
        warmup_scores.append(raw_score)
        if len(warmup_scores) % 10 == 0:
            print(f"[{time.strftime('%H:%M:%S')}] 워밍업 {len(warmup_scores)}/{WARMUP_FRAMES}  score={raw_score:.2f}")
        if len(warmup_scores) >= WARMUP_FRAMES:
            # 중간값 1.5배 초과 스파이크 제거 → 워밍업 중 잠깐 사람 있어도 정확한 baseline
            arr    = np.array(warmup_scores)
            median = np.median(arr)
            clean  = arr[arr <= median * 1.5]
            if len(clean) < 10:
                clean = arr  # 필터 후 너무 적으면 전체 사용
            bg_score     = float(np.percentile(clean, 20))  # 하위 20th
            smooth_score = bg_score
            removed      = len(arr) - len(clean)
            print(f"[완료] 스파이크 {removed}개 제거 | 초기 배경={bg_score:.2f} | SAFE<{bg_score*TH_SAFE:.2f} | ALERT>{bg_score*TH_ALERT:.2f}")
        continue

    # ── 현재 점수 비대칭 EMA ───────────────────────────────────────────
    alpha        = SCORE_UP if raw_score > smooth_score else SCORE_DOWN
    smooth_score = (1 - alpha) * smooth_score + alpha * raw_score

    # ── 상대 점수 계산 ─────────────────────────────────────────────────
    relative = smooth_score / (bg_score + 1e-9)

    # ── 배경 업데이트: BG_UPDATE_TH 이하일 때만 (사람 있으면 고정) ──────
    if relative < BG_UPDATE_TH:
        bg_score = (1 - BG_ALPHA) * bg_score + BG_ALPHA * raw_score

    # ── 상태 판단 ──────────────────────────────────────────────────────
    if relative < TH_SAFE:
        raw_state = "SAFE"
    elif relative > TH_ALERT:
        raw_state = "ALERT"
    else:
        raw_state = "DETECTED"

    state_history.append(raw_state)
    final_state = Counter(state_history).most_common(1)[0][0]

    print(
        f"[{time.strftime('%H:%M:%S')}] "
        f"{LABEL_MAP[final_state]} | "
        f"RSSI={rssi_med:.1f} | "
        f"score={raw_score:.2f} rel={relative:.2f} bg={bg_score:.2f}"
    )