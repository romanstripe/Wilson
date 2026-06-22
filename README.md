# WiFi CSI 기반 실내 움직임 감지 시스템

ESP32 보드에서 수집한 **CSI(Channel State Information)** 데이터를 분석해 방 안의 움직임을 실시간으로 감지하고, 브라우저 대시보드에 표시하는 시스템입니다.

[![Live Demo](https://img.shields.io/badge/🧸_Live_Demo-wilsonweb--lake.vercel.app-B89B72?style=for-the-badge)](https://wilsonweb-lake.vercel.app/)

## 프로젝트 소개

WiFi 신호는 사람이나 물체의 움직임에 따라 미세하게 변화합니다. 이 프로젝트는 ESP32에서 수집한 CSI 신호의 진폭 변화를 분석해 별도의 카메라 없이 실내 상태를 감지합니다.

분석 결과는 **SAFE**, **DETECTED**, **ALERT** 세 단계로 구분되며, Flask와 SSE를 통해 웹 대시보드에 실시간으로 전달됩니다. 상단의 라이브 데모에서 실제 화면 구성을 확인할 수 있습니다.

> 이 README는 CSI 데이터 수집부터 움직임 분석, 서버 전송, 대시보드 표시까지의 전체 구현 및 동작 프로세스를 설명합니다.

<br>

---

## 파일 구성

| 파일           | 역할                                                                 |
| -------------- | -------------------------------------------------------------------- |
| `detection.py` | 시리얼 포트에서 CSI 데이터 수신 → 움직임 분석 → 상태 출력            |
| `utils.py`     | CSI 파싱 및 진폭 변환 유틸리티 함수                                  |
| `server.py`    | `detection.py`를 subprocess로 실행, SSE로 브라우저에 실시간 스트리밍 |
| `index.html`   | 실시간 대시보드 UI (SAFE / DETECTED / ALERT 시각화)                  |

---

## 전체 동작 프로세스

```
ESP32 (WiFi CSI 전송)
    │  시리얼(COM4, 115200bps)
    ▼
detection.py  ←─── utils.py (파싱/진폭변환)
    │  stdout (텍스트 로그)
    ▼
server.py (subprocess + Flask)
    │  Server-Sent Events (SSE, /events)
    ▼
index.html (브라우저 대시보드)
```

---

## 각 단계 상세 설명

### 1. ESP32 → detection.py (시리얼 수신)

ESP32가 WiFi 패킷의 CSI 데이터를 아래 형식으로 시리얼 출력합니다:

```
CSI_DATA,RSSI=-36,10,-3,5,-8,...  (128개 정수값)
```

`utils.py`의 함수가 이를 처리합니다:

- **`parse_csi_line(line, csi_len=128)`** — `CSI_DATA`로 시작하는 줄에서 RSSI와 128개 CSI 정수값 추출
- **`csi_to_amp(values, csi_len=128)`** — 복소수(실수부·허수부 쌍)를 진폭으로 변환:  
  $A_i = \sqrt{I_i^2 + Q_i^2}$  
  → 64개 서브캐리어 진폭 배열 반환

---

### 2. detection.py — 움직임 분석

#### 워밍업 단계 (시작 후 ~15초)

- **방에서 나간 상태**에서 60프레임의 CSI 진폭을 수집
- 중간값 × 1.5를 초과하는 스파이크 프레임 자동 제거 (잠깐 사람 있어도 기준선 오염 방지)
- 남은 프레임의 하위 20th percentile → **초기 배경값(`bg_score`)** 결정

#### 실시간 분석 단계

슬라이딩 윈도우 (`WINDOW_SIZE=20`, 약 3초 분량)를 기반으로 매 0.15초마다 평가합니다.

**motion score 계산:**
$$\text{score} = \frac{1}{64} \sum_{k=1}^{64} \sigma_k(\text{window})$$

각 서브캐리어($k$)의 시간축 표준편차를 평균냅니다. 서브캐리어별로 개별 계산하기 때문에 신호 상쇄 없이 움직임에 민감하게 반응합니다.

**비대칭 EMA 스무딩:**

| 방향               | α    | 효과                         |
| ------------------ | ---- | ---------------------------- |
| 상승 (움직임 감지) | 0.45 | 즉시 반응                    |
| 하강 (조용해질 때) | 0.10 | 천천히 복귀 → 상태 오래 유지 |

**상대 점수:**

$$
\mathrm{rel} = \frac{\mathrm{smoothScore}}{\mathrm{bgScore}}
$$

**상태 판정:**

| rel 값    | 상태                    |
| --------- | ----------------------- |
| < 1.6     | 🟢 SAFE — 움직임 없음   |
| 1.6 ~ 2.0 | 🟡 DETECTED — 존재 감지 |
| > 2.0     | 🔴 ALERT — 움직임 감지  |

**적응형 배경 업데이트:**  
`rel < 1.08`일 때만 `bg_score`를 EMA로 천천히 갱신합니다. 사람이 있으면 배경이 고정되어 SAFE로 오분류되지 않습니다.

**최종 상태:** 최근 12 프레임의 다수결(majority vote)로 안정화합니다.

**출력 예시:**

```
[19:50:25] 🔴 ALERT    | Movement Detected | RSSI=-36.0 | score=12.13 rel=2.60 bg=5.94
```

---

### 3. server.py — subprocess + SSE 브리지

`detection.py`를 서브프로세스로 실행하고 그 stdout을 파싱해 브라우저로 스트리밍합니다.

**주요 처리:**

```
server.py 시작
    ├─ Thread: _run_detection()
    │       └─ subprocess.Popen(detection.py, -u, PYTHONUNBUFFERED=1, PYTHONIOENCODING=utf-8)
    │               └─ stdout 한 줄씩 읽기
    │                       └─ 정규식으로 파싱 → JSON → SSE broadcast
    │
    ├─ Thread: _keepalive()
    │       └─ 20초마다 SSE keepalive 전송 (브라우저 연결 유지)
    │
    └─ Flask: GET /events  → SSE 스트림
              GET /        → index.html 반환
```

**subprocess 설정 포인트:**

- `-u` 플래그 + `PYTHONUNBUFFERED=1` — Windows에서 stdout 버퍼링 방지 (없으면 데이터가 안 옴)
- `PYTHONIOENCODING=utf-8` — 이모지(🟢 🔴) 출력 시 cp949 인코딩 오류 방지
- `detection.py` 종료 시 3초 후 자동 재시작

**파싱 정규식:**

```
[HH:MM:SS] ... SAFE|DETECTED|ALERT ... RSSI=X ... score=X rel=X bg=X
```

워밍업 중 줄(`워밍업` 키워드 포함)은 `CALIBRATING` 상태로 브라우저에 전송합니다.

---

### 4. index.html — 실시간 대시보드

SSE(`/events`)에 연결해 상태 변경 시 즉시 UI를 업데이트합니다.

| 상태                 | 색상 | 아이콘    | 애니메이션      |
| -------------------- | ---- | --------- | --------------- |
| SAFE                 | 초록 | 방패+체크 | 정적 글로우     |
| DETECTED             | 노란 | 느낌표    | 정적 글로우     |
| ALERT                | 빨간 | 느낌표    | 펄싱 애니메이션 |
| CALIBRATING (워밍업) | 회색 | 스피너    | —               |

하단 수치 패널: **RSSI / Score / Rel / BG** 실시간 표시

---

## 실행 방법

### 요구 사항

```bash
pip install flask pyserial numpy
```

### 실행

```bash
# detection.py만 단독 실행 (터미널 출력만)
python detection.py

# 대시보드 포함 실행 (권장)
python server.py
# → http://localhost:5000 브라우저에서 열기
```

### 워밍업 안내

서버 시작 후 약 15초간 **방에서 나가 있어야** 정확한 배경값이 설정됩니다.  
`[완료]` 메시지가 출력된 후 방에 들어오면 됩니다.

---

## 파라미터 기본값 설정 이유

| 파라미터        | 기본값 | 설명                                         |
| --------------- | ------ | -------------------------------------------- |
| `WARMUP_FRAMES` | 60     | 워밍업 프레임 수 (늘리면 더 정확한 baseline) |
| `TH_SAFE`       | 1.6    | SAFE 임계값 (낮추면 더 민감)                 |
| `TH_ALERT`      | 2.0    | ALERT 임계값                                 |
| `SCORE_DOWN`    | 0.10   | 상태 복귀 속도 (낮추면 ALERT 오래 유지)      |
| `BG_UPDATE_TH`  | 1.08   | 배경 업데이트 허용 비율 (낮추면 배경 고정)   |
