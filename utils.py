import numpy as np

CSI_PREFIX = "CSI_DATA"
RSSI_PREFIX = "RSSI="


def parse_csi_line(
    line: str, csi_len: int = 128
) -> tuple[int | None, list[int] | None]:
    """시리얼 데이터에서 RSSI와 CSI 정수 배열 추출."""
    if not line.startswith(CSI_PREFIX):
        return None, None

    fields = line.strip().split(",")
    rssi = None
    csi_values = []

    for field in fields[1:]:
        if field.startswith(RSSI_PREFIX):
            try:
                rssi = int(field.removeprefix(RSSI_PREFIX))
            except ValueError:
                rssi = None
            continue

        try:
            csi_values.append(int(field))
        except ValueError:
            continue  # 깨진 필드 제외

    if rssi is None or len(csi_values) < csi_len:
        return None, None

    return rssi, csi_values[:csi_len]


def csi_to_amp(values: list[int], csi_len: int = 128) -> np.ndarray:
    """I/Q 쌍을 서브캐리어 진폭 배열로 변환."""
    value_count = min(len(values), csi_len)
    value_count -= value_count % 2
    pairs = np.asarray(values[:value_count], dtype=float).reshape(-1, 2)
    return np.hypot(pairs[:, 0], pairs[:, 1])
