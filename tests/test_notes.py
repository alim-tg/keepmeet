from keepmeet import knowledge, note_formats
from keepmeet.formatter import _split_format, _split_names, build_prompt


def test_title_picks_obvious_formats():
    assert note_formats.resolve(None, "Team Daily - 2026-10-09") == "daily"
    assert note_formats.resolve(None, "Sprint 42 planning") == "planning"
    assert note_formats.resolve(None, "Q3 retro") == "retro"
    assert note_formats.resolve(None, "CM possible contract updates discussion") == note_formats.AUTO


def test_explicit_choice_wins_over_title():
    assert note_formats.resolve("technical", "Team Daily") == "technical"
    assert note_formats.resolve("nonsense", "Team Daily") == "daily"


def test_fixed_prompt_contains_only_that_structure():
    prompt = build_prompt("2026-10-13", "Shipping design", "technical")
    assert "## Options considered" in prompt
    assert "## Updates" not in prompt
    assert "<meeting_type>technical</meeting_type>" in prompt


def test_auto_prompt_lists_every_format_without_biased_example():
    prompt = build_prompt("2026-10-13", "Sync", note_formats.AUTO)
    for key in note_formats.FORMATS:
        assert f"### {key}:" in prompt
    assert "<meeting_type>KEY</meeting_type>" in prompt


def test_output_blocks_are_stripped():
    output = "## Summary\n- ok\n<meeting_type>planning</meeting_type>\n<speaker_names>\n{\"SPEAKER_01\": \"Peter\"}\n</speaker_names>"
    rest, used = _split_format(output)
    notes, names = _split_names(rest)
    assert used == "planning"
    assert names == {"SPEAKER_01": "Peter"}
    assert notes == "## Summary\n- ok"


def test_knowledge_loads_glossary_and_index(tmp_path):
    memory = tmp_path / "memory"
    memory.mkdir()
    (memory / "glossary.md").write_text(
        "---\nsummary: x\n---\n\n# Glossary\n\n| Term | Meaning | Node |\n|---|---|---|\n"
        "| **BLS** | Billing Service — invoices and payments | `repo:billing` |\n"
        "| **INV / stock engine** | Inventory Service — stock levels | `repo:inventory` |\n",
        encoding="utf-8",
    )
    (memory / "INDEX.md").write_text("# Memory index\n\n- [billing-service](repos/s.md) — labels\n", encoding="utf-8")
    kb = knowledge.load(str(tmp_path))
    assert "Billing Service" in kb.digest and "billing-service" in kb.digest
    assert kb.terms == ["BLS", "Billing Service", "INV", "stock engine", "Inventory Service"]
    prompt = build_prompt("2026-10-13", "x", "daily", knowledge=kb, lookups=True)
    assert "<system_knowledge>" in prompt and str(tmp_path) in prompt


def test_knowledge_reads_files_at_the_folder_root(tmp_path):
    (tmp_path / "Glossary.md").write_text("| **CRM** | Customer Relations Manager — leads |\n", encoding="utf-8")
    kb = knowledge.load(str(tmp_path))
    assert kb.terms == ["CRM", "Customer Relations Manager"]
    assert "Systems index" not in kb.digest


def test_missing_knowledge_path_is_ignored(tmp_path):
    assert knowledge.load(str(tmp_path / "nope")) is None
    assert knowledge.load("") is None
