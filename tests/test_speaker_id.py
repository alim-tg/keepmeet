from keepmeet.asr import cleanup
from keepmeet.speaker_id import combine, parse_identification


def voice(name, confidence, merged=False):
    return {"name": name, "confidence": confidence, "merged": merged, "slug": name.lower()}


def test_oct9_case_conversation_fixes_weak_voice_and_keeps_strong():
    speakers = ["SPEAKER_01", "SPEAKER_02", "SPEAKER_03", "SPEAKER_04"]
    voice_matches = {
        "SPEAKER_02": voice("Ivan", 0.84),
        "SPEAKER_03": voice("Maria", 0.70),
    }
    conversation = {
        "SPEAKER_01": {"name": "Alexander", "confidence": "high", "evidence": "Саш, что у тебя?"},
        "SPEAKER_02": {"name": "Maria", "confidence": "medium", "evidence": "wrong guess"},
        "SPEAKER_04": {"name": "Peter", "confidence": "high", "evidence": "runs the release"},
    }
    decided = combine(speakers, voice_matches, conversation, same_voice={("SPEAKER_01", "SPEAKER_02"): 0.56})
    names = {sid: info["name"] for sid, info in decided.items()}
    assert names == {"SPEAKER_01": "Alexander", "SPEAKER_02": "Ivan", "SPEAKER_03": "Maria", "SPEAKER_04": "Peter"}
    assert decided["SPEAKER_01"]["source"] == "conversation"
    assert decided["SPEAKER_02"]["source"] == "voice"


def test_same_name_twice_is_dropped_unless_voices_match():
    voice_matches = {"SPEAKER_01": voice("Ivan", 0.70), "SPEAKER_02": voice("Ivan", 0.84)}
    decided = combine(["SPEAKER_01", "SPEAKER_02"], voice_matches, {}, same_voice={("SPEAKER_01", "SPEAKER_02"): 0.56})
    assert set(decided) == {"SPEAKER_02"}
    decided = combine(["SPEAKER_01", "SPEAKER_02"], voice_matches, {}, same_voice={("SPEAKER_01", "SPEAKER_02"): 0.82})
    assert decided["SPEAKER_01"]["merged"] is True


def test_conversation_agreeing_with_voice_is_marked():
    decided = combine(
        ["SPEAKER_00"], {"SPEAKER_00": voice("Olga", 0.68)},
        {"SPEAKER_00": {"name": "olga", "confidence": "high", "evidence": "Оля, что у тебя?"}}, {},
    )
    assert decided["SPEAKER_00"]["source"] == "voice+conversation"


def test_parse_keeps_only_confident_known_labels():
    output = '''Some text
<speakers>
{"SPEAKER_01": {"name": "Alexander", "confidence": "high", "evidence": "x"},
 "SPEAKER_04": {"name": null, "confidence": "low", "evidence": "never addressed"},
 "SPEAKER_09": {"name": "Ghost", "confidence": "high", "evidence": "not a label"},
 "SPEAKER_02": {"name": "Ivan", "confidence": "low", "evidence": "guess"}}
</speakers>'''
    parsed = parse_identification(output, {"SPEAKER_01", "SPEAKER_02", "SPEAKER_04"})
    assert list(parsed) == ["SPEAKER_01"]
    assert parse_identification("no block", {"SPEAKER_01"}) == {}


def test_fake_credit_split_across_segments_is_removed():
    segments = [
        {"start": 0.0, "end": 1.0, "text": "Bye-bye."},
        {"start": 1.0, "end": 2.0, "text": "Субтитры"},
        {"start": 2.0, "end": 3.0, "text": "создавал DimaTorzok"},
    ]
    words = [
        {"word": "Bye-bye.", "start": 0.1, "end": 0.8},
        {"word": "Субтитры", "start": 1.1, "end": 1.8},
        {"word": "создавал", "start": 2.1, "end": 2.5},
        {"word": "DimaTorzok", "start": 2.5, "end": 2.9},
    ]
    assert [w["word"] for w in cleanup.clean_words(segments, words)] == ["Bye-bye."]
