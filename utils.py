import numpy as np

def parse_csi_line(line, csi_len=128):
    if not line.startswith("CSI_DATA"):
        return None, None

    parts = line.strip().split(",")
    rssi = None
    csi_values = []

    for p in parts[1:]:
        if p.startswith("RSSI="):
            try:
                rssi = int(p.replace("RSSI=", ""))
            except:
                rssi = None
        else:
            try:
                csi_values.append(int(p))
            except:
                pass

    if rssi is None or len(csi_values) < csi_len:
        return None, None

    return rssi, csi_values[:csi_len]


def csi_to_amp(values, csi_len=128):
    return np.array([
        np.sqrt(values[i] ** 2 + values[i + 1] ** 2)
        for i in range(0, csi_len - 1, 2)
    ])