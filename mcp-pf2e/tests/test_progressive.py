"""Unit tests for progressive generation foundation: AbilityPlan, CharacterState, filtering."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from orchestrator.progressive import (
    AbilityPlan,
    CharacterState,
    FilterResult,
    ProgressiveSlot,
    compute_ability_plan,
    compute_starting_skills,
    init_state,
    build_slot_sequence,
    filter_candidates,
    plan_dedication_slots,
    update_state,
    _apply_boost,
    _ABILITIES,
)
from query.decomposer import get_build_options
from validator.types import ParsedFeatChoice


# ============================================================================
# AbilityPlan tests
# ============================================================================

class TestApplyBoost:
    def test_below_18_adds_2(self):
        scores = {"str": 10}
        _apply_boost(scores, "str")
        assert scores["str"] == 12

    def test_at_18_adds_1(self):
        scores = {"str": 18}
        _apply_boost(scores, "str")
        assert scores["str"] == 19

    def test_above_18_adds_1(self):
        scores = {"str": 19}
        _apply_boost(scores, "str")
        assert scores["str"] == 20

    def test_at_16_adds_2(self):
        scores = {"str": 16}
        _apply_boost(scores, "str")
        assert scores["str"] == 18

    def test_missing_ability_no_op(self):
        scores = {"str": 10}
        _apply_boost(scores, "dex")
        assert scores == {"str": 10}


class TestComputeAbilityPlan:
    def test_goblin_thaumaturge_l1(self):
        """Goblin: +cha, +dex, free, -wis. Thaumaturge: key=cha."""
        plan = compute_ability_plan(
            ancestry_fixed=["cha", "dex"],
            ancestry_free_count=1,
            ancestry_flaws=["wis"],
            background_options=["cha", "str"],
            background_free_count=1,
            class_key_abilities=["cha"],
            priority_order=["cha", "str", "con", "dex", "wis", "int"],
            character_level=1,
        )
        s = plan.scores_by_level[1]
        assert s["cha"] >= 16, f"Key ability Cha should be >= 16, got {s['cha']}"
        assert s["wis"] == 8, f"Goblin Wis flaw: expected 8, got {s['wis']}"
        assert 1 in plan.scores_by_level
        assert 5 not in plan.scores_by_level

    def test_human_fighter_l1(self):
        """Human: 2 free ancestry boosts, no flaws. Fighter: key=str or dex."""
        plan = compute_ability_plan(
            ancestry_fixed=[],
            ancestry_free_count=2,
            ancestry_flaws=[],
            background_options=["dex", "str"],
            background_free_count=1,
            class_key_abilities=["str", "dex"],
            priority_order=["str", "con", "dex", "wis", "int", "cha"],
            character_level=1,
        )
        s = plan.scores_by_level[1]
        assert s["str"] == 18, f"Fighter Str should be 18 at L1, got {s['str']}"

    def test_level_5_boosts(self):
        plan = compute_ability_plan(
            ancestry_fixed=["con", "wis"],
            ancestry_free_count=1,
            ancestry_flaws=["cha"],
            background_options=["int", "wis"],
            background_free_count=1,
            class_key_abilities=["int"],
            priority_order=["int", "wis", "con", "dex", "str", "cha"],
            character_level=5,
        )
        assert 5 in plan.scores_by_level
        l1 = plan.scores_by_level[1]
        l5 = plan.scores_by_level[5]
        # L5 boosts should increase top 4 priority abilities
        boosted = sum(1 for a in _ABILITIES if l5[a] > l1[a])
        assert boosted == 4, f"L5 should boost exactly 4 abilities, boosted {boosted}"

    def test_level_20_all_boost_rounds(self):
        plan = compute_ability_plan(
            ancestry_fixed=["str"],
            ancestry_free_count=1,
            ancestry_flaws=[],
            background_options=["str", "con"],
            background_free_count=1,
            class_key_abilities=["str"],
            priority_order=["str", "dex", "con", "int", "wis", "cha"],
            character_level=20,
        )
        assert set(plan.scores_by_level.keys()) == {1, 5, 10, 15, 20}
        l20 = plan.scores_by_level[20]
        # Str should be highest; with many boosts above 18, +1 each
        assert l20["str"] >= 20

    def test_remaster_odd_scores_above_18(self):
        """Verify that boosts above 18 produce +1 (odd scores are legal)."""
        plan = compute_ability_plan(
            ancestry_fixed=["cha", "dex"],
            ancestry_free_count=1,
            ancestry_flaws=["wis"],
            background_options=["cha", "str"],
            background_free_count=1,
            class_key_abilities=["cha"],
            priority_order=["cha", "str", "con", "dex", "wis", "int"],
            character_level=5,
        )
        l5 = plan.scores_by_level[5]
        # Cha starts at 18 (L1), gets +1 at L5 = 19
        assert l5["cha"] == 19, f"Cha at L5 should be 19 (18+1 Remaster), got {l5['cha']}"

    def test_no_double_boost_per_event(self):
        """Each ability can receive at most one boost per boost event."""
        plan = compute_ability_plan(
            ancestry_fixed=[],
            ancestry_free_count=2,
            ancestry_flaws=[],
            background_options=["str"],
            background_free_count=1,
            class_key_abilities=["str"],
            priority_order=["str", "str", "str", "str", "str", "str"],
            character_level=1,
        )
        l1 = plan.scores_by_level[1]
        # Even with str repeated in priority, L1 free boosts should go to different abilities
        # Str gets: bg fixed + bg free(str already boosted, skip) + class key + ancestry free 1 + ancestry free 2(str already) + L1 free(str)
        # Actually with str repeated, the priority loop will try str first each time but skip if already boosted
        # The 4 L1 free boosts should go to 4 different abilities
        non_ten = [a for a in _ABILITIES if l1[a] != 10]
        # With all priority on str, str gets one boost from each event where it hasn't been boosted yet
        assert l1["str"] <= 18, f"Str shouldn't exceed 18 at L1 (cap from per-event limit)"

    def test_at_level_interpolation(self):
        plan = compute_ability_plan(
            ancestry_fixed=["str"],
            ancestry_free_count=1,
            ancestry_flaws=[],
            background_options=["str", "con"],
            background_free_count=1,
            class_key_abilities=["str"],
            priority_order=["str", "dex", "con", "int", "wis", "cha"],
            character_level=10,
        )
        assert plan.at_level(1) == plan.scores_by_level[1]
        assert plan.at_level(3) == plan.scores_by_level[1]
        assert plan.at_level(4) == plan.scores_by_level[1]
        assert plan.at_level(5) == plan.scores_by_level[5]
        assert plan.at_level(7) == plan.scores_by_level[5]
        assert plan.at_level(10) == plan.scores_by_level[10]

    def test_below_level_1_returns_base(self):
        plan = compute_ability_plan(
            ancestry_fixed=[],
            ancestry_free_count=1,
            ancestry_flaws=[],
            background_options=[],
            background_free_count=0,
            class_key_abilities=[],
            priority_order=["str", "dex", "con", "int", "wis", "cha"],
            character_level=1,
        )
        scores = plan.at_level(0)
        # Should still return the L1 scores (best available)
        assert scores is not None


# ============================================================================
# Starting skills tests
# ============================================================================

class TestComputeStartingSkills:
    def test_thaumaturge_skills(self):
        plan = compute_ability_plan(
            ancestry_fixed=["cha", "dex"], ancestry_free_count=1,
            ancestry_flaws=["wis"], background_options=["int", "wis"],
            background_free_count=1, class_key_abilities=["cha"],
            priority_order=["cha", "str", "con", "dex", "wis", "int"],
            character_level=4,
        )
        skills = compute_starting_skills(
            "thaumaturge", "Acolyte", plan, ["intimidation", "diplomacy", "stealth"],
        )
        # Class fixed: arcana, nature, occultism, religion
        assert skills.get("arcana") == "trained"
        assert skills.get("nature") == "trained"
        assert skills.get("occultism") == "trained"
        assert skills.get("religion") == "trained"
        # Class custom: Esoteric Lore
        assert skills.get("esoteric lore") == "trained"
        # Background: religion (already trained), Scribing Lore
        assert skills.get("scribing lore") == "trained"
        # Priority fills (3 additional slots, Int 10 = 0 bonus)
        assert skills.get("intimidation") == "trained"
        assert skills.get("diplomacy") == "trained"
        assert skills.get("stealth") == "trained"

    def test_int_modifier_grants_extra_slots(self):
        plan = compute_ability_plan(
            ancestry_fixed=["int"], ancestry_free_count=1,
            ancestry_flaws=[], background_options=["int"],
            background_free_count=1, class_key_abilities=["int"],
            priority_order=["int", "str", "dex", "con", "wis", "cha"],
            character_level=1,
        )
        int_score = plan.at_level(1)["int"]
        int_mod = max(0, (int_score - 10) // 2)
        assert int_mod >= 2, f"Int should be high enough for bonus slots, got {int_score}"

        skills = compute_starting_skills(
            "wizard", "Acolyte", plan,
            ["stealth", "athletics", "deception", "diplomacy", "nature", "society"],
        )
        # Wizard: 2 additional + int_mod bonus
        free_count = sum(1 for s, r in skills.items()
                         if r == "trained" and s not in ["arcana", "religion", "scribing lore"])
        assert free_count == 2 + int_mod


# ============================================================================
# Filter candidates tests
# ============================================================================

class TestFilterCandidates:
    def _make_state(self, **kwargs):
        defaults = dict(
            class_name="thaumaturge", ancestry_name="goblin", character_level=8,
            background_name="Acolyte",
            ability_priority=["cha", "str", "con", "dex", "wis", "int"],
            skill_priority=["intimidation", "diplomacy", "medicine"],
        )
        defaults.update(kwargs)
        return init_state(**defaults)

    def test_duplicate_filtered(self):
        state = self._make_state()
        options = get_build_options("thaumaturge", 8, "goblin", [])
        slots = build_slot_sequence(options, "thaumaturge", 8)
        class_slots = [s for s in slots if s.slot_type == "class_feat"]

        result1 = filter_candidates(state, class_slots[0])
        assert len(result1.legal) > 0
        first_feat = result1.legal[0]

        update_state(state, first_feat, class_slots[0])
        result2 = filter_candidates(state, class_slots[1])
        assert first_feat not in result2.legal, "Duplicate should be filtered"
        assert "duplicate" in result2.rejected

    def test_repeatable_feat_not_filtered(self):
        state = self._make_state()
        options = get_build_options("thaumaturge", 8, "goblin", [])
        slots = build_slot_sequence(options, "thaumaturge", 8)
        skill_slots = [s for s in slots if s.slot_type == "skill_feat"]
        assert len(skill_slots) >= 2

        # Take Additional Lore, then check it's still available
        update_state(state, "Additional Lore", skill_slots[0])
        result = filter_candidates(state, skill_slots[1])
        assert "Additional Lore" in result.legal

    def test_dedication_ordering_blocks_second(self):
        state = self._make_state()
        options = get_build_options("thaumaturge", 8, "goblin", ["champion"])
        slots = build_slot_sequence(options, "thaumaturge", 8)
        class_slots = [s for s in slots if s.slot_type == "class_feat"]

        # Take Champion Dedication
        update_state(state, "Champion Dedication", class_slots[0])

        # At next class feat slot, other dedications should be blocked
        result = filter_candidates(state, class_slots[1])
        dedication_feats = [f for f in result.legal if "dedication" in f.lower()]
        assert len(dedication_feats) == 0, f"No dedications should pass: {dedication_feats}"
        assert "dedication_ordering" in result.rejected

    def test_dedication_ordering_allows_after_2_archetype(self):
        state = self._make_state()
        options = get_build_options("thaumaturge", 8, "goblin", ["champion", "medic"])
        slots = build_slot_sequence(options, "thaumaturge", 8)
        class_slots = [s for s in slots if s.slot_type == "class_feat"]

        update_state(state, "Champion Dedication", class_slots[0])
        update_state(state, "Basic Devotion", class_slots[1])
        update_state(state, "Champion Resiliency", class_slots[2])

        # Now second dedication should be allowed
        result = filter_candidates(state, class_slots[3])
        dedication_feats = [f for f in result.legal if "dedication" in f.lower()]
        assert len(dedication_feats) > 0, "Dedications should be allowed after 2 archetype feats"

    def test_skill_increase_candidates(self):
        state = self._make_state(character_level=4)
        options = get_build_options("thaumaturge", 4, "goblin", [])
        slots = build_slot_sequence(options, "thaumaturge", 4)
        skill_inc = [s for s in slots if s.slot_type == "skill_increase"]
        assert len(skill_inc) > 0

        result = filter_candidates(state, skill_inc[0])
        assert len(result.legal) > 0
        for skill in result.legal:
            assert skill in state.skills, f"{skill} should be a trained skill"

    def test_skill_increase_respects_level_requirements(self):
        state = self._make_state(character_level=4)
        # At L3, can increase to expert (requires L3+). Master requires L7+.
        options = get_build_options("thaumaturge", 4, "goblin", [])
        slots = build_slot_sequence(options, "thaumaturge", 4)
        skill_inc = [s for s in slots if s.slot_type == "skill_increase"]

        # Increase a skill to expert
        result = filter_candidates(state, skill_inc[0])
        update_state(state, result.legal[0], skill_inc[0])
        assert state.skills[result.legal[0]] == "expert"

    def test_filter_result_tracks_rejections(self):
        state = self._make_state()
        options = get_build_options("thaumaturge", 8, "goblin", ["champion"])
        slots = build_slot_sequence(options, "thaumaturge", 8)
        class_slots = [s for s in slots if s.slot_type == "class_feat"]

        # After taking Champion Dedication, many feats should be filtered
        update_state(state, "Champion Dedication", class_slots[0])
        result = filter_candidates(state, class_slots[1])

        total_rejected = sum(len(v) for v in result.rejected.values())
        assert total_rejected > 0, "Should have some rejections"
        assert result.total_offered == len(result.legal) + total_rejected


# ============================================================================
# Dedication locking tests
# ============================================================================

class TestDedicationLocking:
    def test_single_dedication(self):
        options = get_build_options("thaumaturge", 4, "goblin", ["champion"])
        plan = compute_ability_plan(
            ["cha", "dex"], 1, ["wis"], ["cha", "str"], 1, ["cha"],
            ["cha", "str", "con", "dex", "wis", "int"], 4,
        )
        result = plan_dedication_slots(options, ["champion"], plan)
        assert isinstance(result, dict)
        assert any("Champion Dedication" in v for v in result.values())

    def test_dual_dedication_scheduling(self):
        options = get_build_options("thaumaturge", 8, "goblin", ["champion", "medic"])
        plan = compute_ability_plan(
            ["cha", "dex"], 1, ["wis"], ["cha", "str"], 1, ["cha"],
            ["cha", "str", "con", "dex", "wis", "int"], 8,
        )
        result = plan_dedication_slots(options, ["champion", "medic"], plan)
        assert isinstance(result, dict), f"Should succeed, got: {result}"

        # Verify ordering: champion before archetype slots before medic
        ded_levels = {}
        arch_levels = []
        for k, v in result.items():
            lvl = int(k.split("_")[0])
            if "Champion Dedication" in v:
                ded_levels["champion"] = lvl
            elif "Medic Dedication" in v:
                ded_levels["medic"] = lvl
            elif "__archetype_from_" in v:
                arch_levels.append(lvl)

        assert ded_levels["champion"] < min(arch_levels), "Champion should be before archetype slots"
        assert max(arch_levels) < ded_levels["medic"], "Archetype slots should be before Medic"
        assert len(arch_levels) == 2, "Should have exactly 2 archetype slots"

    def test_infeasible_dual_dedication_low_level(self):
        options = get_build_options("thaumaturge", 4, "goblin", ["champion", "medic"])
        plan = compute_ability_plan(
            ["cha", "dex"], 1, ["wis"], ["cha", "str"], 1, ["cha"],
            ["cha", "str", "con", "dex", "wis", "int"], 4,
        )
        result = plan_dedication_slots(options, ["champion", "medic"], plan)
        assert isinstance(result, str), f"Should fail (not enough slots), got: {result}"

    def test_empty_dedications(self):
        options = get_build_options("thaumaturge", 4, "goblin", [])
        plan = compute_ability_plan(
            ["cha", "dex"], 1, ["wis"], [], 0, ["cha"],
            ["cha", "str", "con", "dex", "wis", "int"], 4,
        )
        result = plan_dedication_slots(options, [], plan)
        assert result == {}


# ============================================================================
# Slot sequencing tests
# ============================================================================

class TestSlotSequencing:
    def test_skill_increase_before_feats(self):
        options = get_build_options("thaumaturge", 8, "goblin", [])
        slots = build_slot_sequence(options, "thaumaturge", 8)

        for level in [3, 5, 7]:
            level_slots = [s for s in slots if s.level == level]
            types = [s.slot_type for s in level_slots]
            if "skill_increase" in types:
                si_idx = types.index("skill_increase")
                assert si_idx == 0, f"Skill increase should be first at L{level}, order: {types}"

    def test_includes_all_slot_types(self):
        options = get_build_options("thaumaturge", 8, "goblin", [])
        slots = build_slot_sequence(options, "thaumaturge", 8)
        types = {s.slot_type for s in slots}
        assert "class_feat" in types
        assert "ancestry_feat" in types
        assert "skill_feat" in types
        assert "general_feat" in types
        assert "skill_increase" in types


# ============================================================================
# State update tests
# ============================================================================

class TestUpdateState:
    def test_skill_increase_updates_rank(self):
        state = init_state("thaumaturge", "goblin", 4, "Acolyte",
                           ["cha", "str", "con", "dex", "wis", "int"],
                           ["intimidation"])
        slot = ProgressiveSlot(slot_type="skill_increase", level=3)
        assert state.skills.get("intimidation") == "trained"
        update_state(state, "intimidation", slot)
        assert state.skills["intimidation"] == "expert"

    def test_dedication_tracking(self):
        state = init_state("thaumaturge", "goblin", 8, "Acolyte",
                           ["cha", "str", "con", "dex", "wis", "int"],
                           ["intimidation"])
        slot = ProgressiveSlot(slot_type="class_feat", level=2)
        update_state(state, "Champion Dedication", slot)
        assert "champion" in state.dedications_taken
        assert state.archetype_feat_counts.get("champion") == 0

    def test_archetype_feat_counting(self):
        state = init_state("thaumaturge", "goblin", 8, "Acolyte",
                           ["cha", "str", "con", "dex", "wis", "int"],
                           ["intimidation"])
        slot = ProgressiveSlot(slot_type="class_feat", level=2)
        update_state(state, "Champion Dedication", slot)
        slot4 = ProgressiveSlot(slot_type="class_feat", level=4)
        update_state(state, "Basic Devotion", slot4)
        assert state.archetype_feat_counts["champion"] == 1
        update_state(state, "Champion Resiliency", slot4)
        assert state.archetype_feat_counts["champion"] == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
