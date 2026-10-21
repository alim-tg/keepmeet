from ..self_voice import SELF_SPEAKER


def _filter_diarization_noise(segs: list[tuple], min_dur: float = 0.25) -> list[tuple]:
    kept = []
    for start, end, speaker in segs:
        dur = end - start
        if dur >= min_dur:
            kept.append((start, end, speaker))
            continue
        dominated = False
        for o_start, o_end, o_speaker in segs:
            if o_speaker == speaker:
                continue
            overlap = max(0, min(end, o_end) - max(start, o_start))
            if overlap > dur * 0.5 and (o_end - o_start) > dur * 3:
                dominated = True
                break
        if not dominated:
            kept.append((start, end, speaker))
    return kept


def assign_speakers(turns: list[tuple], words: list[dict]) -> list[dict]:
    if not words:
        return []
    if not turns:
        return _words_to_segments([{**w, "speaker": "SPEAKER_00"} for w in words])

    diar_segs = _filter_diarization_noise(sorted(turns, key=lambda x: x[0]))

    boundaries = []
    for i in range(1, len(diar_segs)):
        boundaries.append({
            "time": (diar_segs[i - 1][1] + diar_segs[i][0]) / 2,
            "prev_speaker": diar_segs[i - 1][2],
            "next_speaker": diar_segs[i][2],
            "prev_end": diar_segs[i - 1][1],
            "next_start": diar_segs[i][0],
        })

    all_words = sorted((dict(w) for w in words), key=lambda w: w["start"])
    deduped = [all_words[0]]
    for w in all_words[1:]:
        if w["start"] - deduped[-1]["start"] < 0.1 and w["word"] == deduped[-1]["word"]:
            continue
        deduped.append(w)
    all_words = deduped

    for w in all_words:
        mid = (w["start"] + w.get("end", w["start"])) / 2
        best_speaker = None
        best_overlap = 0.0
        for ds_start, ds_end, ds_speaker in diar_segs:
            if ds_end < w["start"] - 1.0:
                continue
            if ds_start > w.get("end", w["start"]) + 1.0:
                break
            overlap = max(0, min(ds_end, w.get("end", w["start"])) - max(ds_start, w["start"]))
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = ds_speaker
        if not best_speaker:
            min_dist = float("inf")
            for ds_start, ds_end, ds_speaker in diar_segs:
                dist = min(abs(mid - ds_start), abs(mid - ds_end))
                if dist < min_dist:
                    min_dist = dist
                    best_speaker = ds_speaker
        w["speaker"] = best_speaker

    SNAP_TOLERANCE = 4.0
    SELF_SNAP_TOLERANCE = 1.0
    for b in boundaries:
        if b["prev_speaker"] == b["next_speaker"]:
            continue
        bt = b["time"]
        tolerance = SELF_SNAP_TOLERANCE if SELF_SPEAKER in (b["prev_speaker"], b["next_speaker"]) else SNAP_TOLERANCE
        nearby_idx = []
        for i, w in enumerate(all_words):
            w_mid = (w["start"] + w.get("end", w["start"])) / 2
            if abs(w_mid - bt) < tolerance:
                nearby_idx.append(i)
        if not nearby_idx:
            continue

        best_split = None
        best_score = -1.0
        for i in nearby_idx:
            if i == 0:
                continue
            prev_end = all_words[i - 1].get("end", all_words[i - 1]["start"])
            cur_start = all_words[i]["start"]
            gap = cur_start - prev_end
            if gap < 0.05:
                continue
            score = gap
            prev_text = (all_words[i - 1].get("word") or all_words[i - 1].get("text", "")).strip()
            if prev_text and prev_text[-1] in ".?!":
                score += 2.0
            next_text = (all_words[i].get("word") or all_words[i].get("text", "")).strip()
            if next_text and next_text[0].isupper():
                score += 0.5
            if score > best_score:
                best_score = score
                best_split = i

        if best_split is not None and best_score >= 0.05:
            lo = nearby_idx[0]
            hi = nearby_idx[-1] + 1
            for i in range(lo, best_split):
                all_words[i]["speaker"] = b["prev_speaker"]
            for i in range(best_split, hi):
                all_words[i]["speaker"] = b["next_speaker"]

    return _words_to_segments(all_words)


def _join(words: list[dict]) -> str:
    text = "".join(w.get("raw") or " " + w.get("word", "") for w in words)
    return " ".join(text.split())


def _words_to_segments(all_words: list[dict]) -> list[dict]:
    if not all_words:
        return []

    result = []
    cur_spk = all_words[0].get("speaker")
    cur_words = [all_words[0]]

    for w in all_words[1:]:
        if w.get("speaker") == cur_spk:
            cur_words.append(w)
        else:
            text = _join(cur_words)
            if text:
                result.append({
                    "speaker": cur_spk,
                    "start": cur_words[0]["start"],
                    "end": cur_words[-1].get("end", cur_words[-1]["start"]),
                    "text": text,
                })
            cur_spk = w.get("speaker")
            cur_words = [w]

    text = _join(cur_words)
    if text:
        result.append({
            "speaker": cur_spk,
            "start": cur_words[0]["start"],
            "end": cur_words[-1].get("end", cur_words[-1]["start"]),
            "text": text,
        })

    merged = _merge_same_speaker(result)
    return _merge_sandwiched(merged)


def _merge_same_speaker(segments: list[dict]) -> list[dict]:
    if not segments:
        return segments
    merged = [segments[0]]
    for cur in segments[1:]:
        prev = merged[-1]
        if cur.get("speaker") == prev.get("speaker"):
            merged[-1] = {
                **prev,
                "end": cur["end"],
                "text": (prev.get("text", "") + " " + cur.get("text", "")).strip(),
            }
        else:
            merged.append(cur)
    return merged


def _merge_sandwiched(segments: list[dict], max_duration: float = 5.0) -> list[dict]:
    if len(segments) < 3:
        return segments
    changed = True
    while changed:
        changed = False
        new_segs = [segments[0]]
        i = 1
        while i < len(segments):
            cur = segments[i]
            prev = new_segs[-1]
            cur_dur = cur.get("end", 0) - cur.get("start", 0)
            nxt = segments[i + 1] if i + 1 < len(segments) else None
            if (
                cur_dur < max_duration
                and cur.get("speaker") != prev.get("speaker")
                and nxt
                and nxt.get("speaker") == prev.get("speaker")
            ):
                gap_before = cur.get("start", 0) - prev.get("end", 0)
                gap_after = nxt.get("start", 0) - cur.get("end", 0)
                if gap_before < 2.0 and gap_after < 2.0:
                    new_segs[-1] = {
                        **prev,
                        "end": nxt["end"],
                        "text": (prev.get("text", "") + " " + cur.get("text", "") + " " + nxt.get("text", "")).strip(),
                    }
                    i += 2
                    changed = True
                    continue
            new_segs.append(cur)
            i += 1
        segments = new_segs
    return segments
