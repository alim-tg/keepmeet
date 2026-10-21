import json

import numpy as np
import pytest

from keepmeet.asr import chunking, cleanup, deepinfra, vocabulary
from keepmeet.asr.alignment import assign_speakers
from keepmeet.asr.audio import SAMPLE_RATE
from keepmeet.asr.language import LanguageChoice, classify


def test_windows_pack_speech_up_to_target():
    spans = [(0, 10), (12, 22), (25, 40), (41, 100)]
    windows = chunking.build_windows(spans, target=30)
    assert all(sum(e - s for s, e in w) <= 30 for w in windows)
    assert sum(e - s for w in windows for s, e in w) == pytest.approx(10 + 10 + 15 + 59)


def test_chunks_split_on_language_change_and_size():
    windows = [[(0, 30)], [(30, 60)], [(60, 90)], [(90, 120)], [(120, 150)]]
    choices = [LanguageChoice(lang, [lang]) for lang in ["ru", "ru", "en", "en", "ru"]]
    chunks = chunking.group_chunks(windows, choices, max_speech=60)
    assert [(c.language, c.speech_seconds) for c in chunks] == [("ru", 60), ("en", 60), ("ru", 30)]


def test_ambiguous_windows_get_their_own_chunk():
    windows = [[(0, 30)], [(30, 60)], [(60, 90)]]
    choices = [LanguageChoice("ru", ["ru"]), LanguageChoice("ru", ["ru", "en"]), LanguageChoice("ru", ["ru"])]
    chunks = chunking.group_chunks(windows, choices, max_speech=90)
    assert [c.candidates for c in chunks] == [["ru"], ["ru", "en"], ["ru"]]


def test_time_map_returns_source_times_across_spacers():
    spans = [(10.0, 12.0), (50.0, 53.0)]
    _, time_map = chunking.render(np.zeros(60 * SAMPLE_RATE, dtype=np.float32), spans, spacer=0.3)
    assert time_map.to_source(0.5) == pytest.approx(10.5)
    assert time_map.to_source(2.15) == pytest.approx(12.0)
    assert time_map.to_source(2.3 + 1.0) == pytest.approx(51.0)


def test_render_drops_silence_between_spans():
    samples = np.ones(10 * SAMPLE_RATE, dtype=np.float32)
    audio, time_map = chunking.render(samples, [(0, 1), (8, 9)], spacer=0.5)
    assert len(audio) == int(2.5 * SAMPLE_RATE)
    assert time_map.length == pytest.approx(2.5)


def test_confident_detection_is_used_directly():
    assert classify({"ru": 0.98, "en": 0.02}, "ru") == LanguageChoice("ru", ["ru"])
    assert classify({"ru": 0.03, "en": 0.97}, "ru") == LanguageChoice("en", ["en"])


def test_unsure_detection_keeps_both_candidates():
    assert classify({"ru": 0.77, "en": 0.23}, "ru").candidates == ["ru", "en"]
    assert classify({}, "ru") == LanguageChoice("ru", ["ru"])


def test_subtitle_credit_hallucinations_are_removed():
    segments = [
        {"start": 0.0, "end": 2.0, "text": "Редактор субтитров А.Семкин Корректор А.Егорова"},
        {"start": 2.0, "end": 4.0, "text": "Задет только payment adapter в Billing Service."},
    ]
    words = [
        {"word": "Редактор", "start": 0.1, "end": 0.5},
        {"word": "субтитров", "start": 0.5, "end": 1.0},
        {"word": "Задет", "start": 2.1, "end": 2.4},
        {"word": "payment", "start": 2.5, "end": 2.8},
        {"word": "adapter", "start": 2.8, "end": 3.1},
        {"word": "Billing", "start": 3.2, "end": 3.5},
        {"word": "Service.", "start": 3.5, "end": 3.9},
    ]
    kept = [w["word"] for w in cleanup.clean_words(segments, words)]
    assert kept == ["Задет", "payment", "adapter", "Billing", "Service."]


def test_english_terms_at_end_of_russian_sentence_are_kept():
    segments = [{"start": 0.0, "end": 3.0, "text": "надо залить на Stage PR"}]
    words = [{"word": w, "start": i * 0.5, "end": i * 0.5 + 0.4} for i, w in enumerate("надо залить на Stage PR".split())]
    assert [w["word"] for w in cleanup.clean_words(segments, words)][-2:] == ["Stage", "PR"]


def test_repetition_loop_is_trimmed():
    text = "да да ок " * 10
    segments = [{"start": 0.0, "end": 30.0, "text": text}]
    words = [{"word": w, "start": i, "end": i + 0.5} for i, w in enumerate(text.split())]
    assert len(cleanup.clean_words(segments, words)) < 10


def test_prompt_is_in_chunk_language_and_bounded():
    prompt = vocabulary.build_prompt(["Alex", "Maria"], ["Billing Service", "CRM"] * 200, "ru")
    assert prompt.startswith("Рабочая встреча")
    assert "Alex" in prompt and "Billing Service" in prompt
    assert len(prompt) <= vocabulary.MAX_PROMPT_CHARS
    assert vocabulary.build_prompt(["Alex"], [], "en").startswith("Engineering team meeting")


def test_terms_harvested_from_russian_transcripts(tmp_path):
    job = {"language": "ru", "segments": [
        {"text": "Залили Billing Service на Stage, CRM не трогаем"},
        {"text": "Billing Service работает, CRM ок, Maria смотрит"},
        {"text": "We have not shipped that order yet, we have to check the order"},
        {"text": "We have not shipped that order yet, we have to check the order"},
    ]}
    (tmp_path / "a.json").write_text(json.dumps(job), encoding="utf-8")
    terms = vocabulary.harvest_terms(tmp_path, exclude={"maria"})
    assert "Billing Service" in terms and "CRM" in terms
    assert "Maria" not in terms
    assert not {"We", "have", "order", "not"} & set(terms)


def test_speakers_assigned_from_turns():
    turns = [(0.0, 5.0, "SPEAKER_00"), (5.5, 10.0, "SELF")]
    words = [{"word": w, "start": t, "end": t + 0.4} for w, t in [("Привет.", 1.0), ("Как", 2.0), ("дела?", 2.5), ("Норм.", 6.0)]]
    segments = assign_speakers(turns, words)
    assert [(s["speaker"], s["text"]) for s in segments] == [("SPEAKER_00", "Привет. Как дела?"), ("SELF", "Норм.")]


class _Response:
    def __init__(self, status, payload):
        self.status_code, self._payload, self.text = status, payload, json.dumps(payload)

    def json(self):
        return self._payload


def test_deepinfra_retries_then_drops_prompt_when_empty(monkeypatch):
    calls = []
    replies = [
        _Response(503, {"detail": "busy"}),
        _Response(200, {"segments": None, "words": None}),
        _Response(200, {"segments": [{"start": 0, "end": 1, "text": "Привет"}], "words": [{"word": " Привет", "start": 0, "end": 1}]}),
    ]

    def fake_post(url, headers, files, data, timeout):
        calls.append(dict(data))
        return replies.pop(0)

    monkeypatch.setattr(deepinfra.requests, "post", fake_post)
    monkeypatch.setattr(deepinfra.time, "sleep", lambda s: None)
    result = deepinfra.transcribe(b"wav", "key", "whisper-large-v3", "ru", "Участники: Alex")
    assert [w["word"] for w in result["words"]] == ["Привет"]
    assert "initial_prompt" in calls[1] and "initial_prompt" not in calls[2]


def test_word_suffixes_stay_attached():
    turns = [(0.0, 5.0, "SPEAKER_00")]
    words = [
        {"word": "Что", "raw": " Что", "start": 0.1, "end": 0.3},
        {"word": "-то", "raw": "-то", "start": 0.3, "end": 0.4},
        {"word": "сломалось.", "raw": " сломалось.", "start": 0.5, "end": 1.0},
    ]
    assert assign_speakers(turns, words)[0]["text"] == "Что-то сломалось."


def test_prompt_never_contains_labels_or_placeholders():
    prompt = vocabulary.build_prompt(["Alex", "Maria"], [], "en")
    assert prompt == "Engineering team meeting. Alex, Maria."
    assert vocabulary.build_prompt([], [], "ru") is None
    assert vocabulary.build_prompt([], ["CRM"], "ru") == "Рабочая встреча команды разработки. CRM."


def test_punctuation_only_tokens_are_dropped():
    words = [{"word": "-.", "start": 0.0, "end": 0.1}, {"word": "Hello,", "start": 0.2, "end": 0.5}]
    assert [w["word"] for w in cleanup.clean_words([], words)] == ["Hello,"]
