"""Tests for llm_eval/discovery.py — pack scanning and template exclusion."""

import pytest

from llm_eval.discovery import discover_packs, get_pack_by_name
from llm_eval.types import ChallengePack


class TestDiscoverPacks:
    def test_discovers_packs(self):
        packs = discover_packs()
        assert len(packs) >= 3  # starter, pf2e, coding
        names = [p.name for p in packs]
        assert "starter" in names
        assert "pf2e" in names
        assert "coding" in names

    def test_excludes_template(self):
        packs = discover_packs()
        names = [p.name for p in packs]
        assert "template" not in names
        assert "_template" not in names

    def test_all_packs_are_challenge_packs(self):
        for pack in discover_packs():
            assert isinstance(pack, ChallengePack)

    def test_all_packs_have_prompts(self):
        for pack in discover_packs():
            prompts = pack.get_prompts()
            assert len(prompts) > 0, f"Pack '{pack.name}' has no prompts"

    def test_all_packs_have_valid_rubrics(self):
        for pack in discover_packs():
            rubric = pack.get_rubric()
            assert len(rubric.criteria) > 0
            total = sum(c.weight for c in rubric.criteria)
            assert abs(total - 1.0) < 0.01, f"Pack '{pack.name}' rubric weights sum to {total}"


class TestGetPackByName:
    def test_find_existing_pack(self):
        pack = get_pack_by_name("starter")
        assert pack is not None
        assert pack.name == "starter"

    def test_find_pf2e(self):
        pack = get_pack_by_name("pf2e")
        assert pack is not None
        assert len(pack.get_prompts()) == 4

    def test_find_coding(self):
        pack = get_pack_by_name("coding")
        assert pack is not None
        assert pack.get_auto_scorer() is not None
        assert pack.get_auto_score_weight() == 0.5

    def test_nonexistent_pack_returns_none(self):
        assert get_pack_by_name("nonexistent") is None
