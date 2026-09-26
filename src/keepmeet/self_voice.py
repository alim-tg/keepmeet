import numpy as np

SELF_SPEAKER = "SELF"
SAMPLE_RATE = 16000
FRAME_SECONDS = 0.03
ACTIVE_ABOVE_FLOOR_DB = 12.0
DOMINANCE_DB = 6.0
MIN_ABSOLUTE_DB = -50.0
MERGE_GAP_SECONDS = 0.4
MIN_REGION_SECONDS = 0.5
SMOOTH_FRAMES = 7


def _frame_db(samples: np.ndarray, frame: int) -> np.ndarray:
    n = len(samples) // frame
    if n == 0:
        return np.zeros(0)
    frames = samples[: n * frame].reshape(n, frame)
    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1))
    return 20 * np.log10(np.maximum(rms, 1e-6))


def _smooth(mask: np.ndarray, width: int) -> np.ndarray:
    if len(mask) < width:
        return mask
    kernel = np.ones(width) / width
    return np.convolve(mask.astype(float), kernel, mode="same") >= 0.5


def detect_self_regions(mic: np.ndarray, system: np.ndarray) -> list[tuple[float, float]]:
    frame = int(SAMPLE_RATE * FRAME_SECONDS)
    length = min(len(mic), len(system))
    if length < frame:
        return []
    mic_db = _frame_db(mic[:length], frame)
    sys_db = _frame_db(system[:length], frame)

    mic_floor = np.percentile(mic_db, 20)
    sys_floor = np.percentile(sys_db, 20)
    mic_rel = mic_db - mic_floor
    sys_rel = sys_db - sys_floor

    mic_active = (mic_rel > ACTIVE_ABOVE_FLOOR_DB) & (mic_db > MIN_ABSOLUTE_DB)
    sys_active = (sys_rel > ACTIVE_ABOVE_FLOOR_DB) & (sys_db > MIN_ABSOLUTE_DB)
    is_self = mic_active & (~sys_active | (mic_rel > sys_rel + DOMINANCE_DB))
    is_self = _smooth(is_self, SMOOTH_FRAMES)

    regions: list[list[float]] = []
    for i in np.flatnonzero(is_self):
        start = i * FRAME_SECONDS
        end = start + FRAME_SECONDS
        if regions and start - regions[-1][1] <= MERGE_GAP_SECONDS:
            regions[-1][1] = end
        else:
            regions.append([start, end])
    return [(s, e) for s, e in regions if e - s >= MIN_REGION_SECONDS]


def overlay_self(turns: list[tuple], self_regions: list[tuple[float, float]]) -> list[tuple]:
    if not self_regions:
        return turns
    result = []
    for start, end, speaker in turns:
        pieces = [(start, end)]
        for s_start, s_end in self_regions:
            next_pieces = []
            for p_start, p_end in pieces:
                if s_end <= p_start or s_start >= p_end:
                    next_pieces.append((p_start, p_end))
                    continue
                if s_start > p_start:
                    next_pieces.append((p_start, s_start))
                if s_end < p_end:
                    next_pieces.append((s_end, p_end))
            pieces = next_pieces
        result.extend((p_start, p_end, speaker) for p_start, p_end in pieces if p_end - p_start > 0.05)
    result.extend((s, e, SELF_SPEAKER) for s, e in self_regions)
    result.sort(key=lambda t: t[0])
    return result
