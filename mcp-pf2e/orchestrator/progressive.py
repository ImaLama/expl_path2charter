"""Progressive generation — ReAct-style agentic loop with deterministic state manager.

Fills feat and skill-increase slots one at a time, filtering candidates against
running state. Ability scores are computed upfront (immutable AbilityPlan).
Dedication ordering is enforced by deterministic slot locking.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from query.static_reader import (
    get_ancestry_boosts,
    get_background_boosts,
    get_background_trained_skills,
    get_class_key_ability,
    get_class_trained_skills,
    get_skill_increase_levels,
    get_feat_data,
    get_feat_slot_levels,
)
from query.types import SlotOptions, BuildOptions
from validator.types import ParsedFeatChoice
from validator.prerequisite import parse_prerequisites, check_prerequisite, Prerequisite


_ABILITIES = ["str", "dex", "con", "int", "wis", "cha"]
_BOOST_LEVELS = [5, 10, 15, 20]
_RANK_ORDER = {"untrained": 0, "trained": 1, "expert": 2, "master": 3, "legendary": 4}
_RANK_BY_INT = {v: k for k, v in _RANK_ORDER.items()}
_REPEATABLE_FEATS = {"additional lore", "assurance", "skill training"}


# ---------------------------------------------------------------------------
# AbilityPlan — computed once at setup, immutable during generation
# ---------------------------------------------------------------------------

@dataclass
class AbilityPlan:
    scores_by_level: dict[int, dict[str, int]]
    priority_order: list[str]

    def at_level(self, level: int) -> dict[str, int]:
        best_key = 1
        for k in self.scores_by_level:
            if k <= level and k > best_key:
                best_key = k
        return self.scores_by_level.get(best_key, {a: 10 for a in _ABILITIES})


def _apply_boost(scores: dict[str, int], ability: str) -> None:
    """Apply a PF2e Remaster ability boost (mutates scores).

    +2 if score < 18, +1 if score >= 18 (PF2e Remaster Player Core rule).
    """
    if ability in scores:
        scores[ability] += 1 if scores[ability] >= 18 else 2


def compute_ability_plan(
    ancestry_fixed: list[str],
    ancestry_free_count: int,
    ancestry_flaws: list[str],
    background_options: list[str],
    background_free_count: int,
    class_key_abilities: list[str],
    priority_order: list[str],
    character_level: int,
) -> AbilityPlan:
    """Build a level-indexed ability score plan from fixed data + priority order.

    Boost application order (PF2e Remaster):
      1. Ancestry fixed boosts and flaws
      2. Background boost (pick from fixed options by priority) + free boost
      3. Class key ability boost
      4. Four L1 free boosts (by priority, one per ability per event)
      5. Level-up boosts at 5/10/15/20 (4 each, by priority, one per ability per event)
    """
    scores = {a: 10 for a in _ABILITIES}

    # 1. Ancestry fixed boosts + flaws
    for a in ancestry_fixed:
        _apply_boost(scores, a)
    for a in ancestry_flaws:
        if a in scores:
            scores[a] -= 2

    # 2. Background: pick the fixed-option boost that best matches priority
    if background_options:
        best_bg = _pick_by_priority(background_options, priority_order, scores)
        _apply_boost(scores, best_bg)

    # Background free boost: pick the highest-priority ability not yet boosted in this event
    bg_boosted = {best_bg} if background_options else set()
    for _ in range(background_free_count):
        for a in priority_order:
            if a in scores and a not in bg_boosted:
                _apply_boost(scores, a)
                bg_boosted.add(a)
                break

    # 3. Class key ability boost
    if class_key_abilities:
        best_key = _pick_by_priority(class_key_abilities, priority_order, scores)
        _apply_boost(scores, best_key)

    # 4. Ancestry free boosts — each to a different ability, by priority
    already_boosted_ancestry = set(ancestry_fixed)
    for _ in range(ancestry_free_count):
        for a in priority_order:
            if a in scores and a not in already_boosted_ancestry:
                _apply_boost(scores, a)
                already_boosted_ancestry.add(a)
                break

    # 5. Four L1 free boosts — each to a different ability, by priority
    l1_boosted: set[str] = set()
    for _ in range(4):
        for a in priority_order:
            if a in scores and a not in l1_boosted:
                _apply_boost(scores, a)
                l1_boosted.add(a)
                break

    scores_by_level = {1: dict(scores)}

    # 6. Level-up boosts at 5/10/15/20
    for boost_level in _BOOST_LEVELS:
        if boost_level > character_level:
            break
        event_boosted: set[str] = set()
        for _ in range(4):
            for a in priority_order:
                if a in scores and a not in event_boosted:
                    _apply_boost(scores, a)
                    event_boosted.add(a)
                    break
        scores_by_level[boost_level] = dict(scores)

    return AbilityPlan(scores_by_level=scores_by_level, priority_order=priority_order)


def _pick_by_priority(options: list[str], priority: list[str], scores: dict[str, int]) -> str:
    """Pick the option that appears earliest in priority order."""
    for a in priority:
        if a in options:
            return a
    return options[0]


# ---------------------------------------------------------------------------
# CharacterState — mutated during the progressive loop
# ---------------------------------------------------------------------------

@dataclass
class CharacterState:
    class_name: str
    ancestry_name: str
    character_level: int

    ability_plan: AbilityPlan

    feats_chosen: list[ParsedFeatChoice] = field(default_factory=list)
    dedications_taken: list[str] = field(default_factory=list)
    archetype_feat_counts: dict[str, int] = field(default_factory=dict)
    locked_slots: dict[str, str] = field(default_factory=dict)

    skills: dict[str, str] = field(default_factory=dict)


def init_state(
    class_name: str,
    ancestry_name: str,
    character_level: int,
    background_name: str,
    ability_priority: list[str],
    skill_priority: list[str],
) -> CharacterState:
    """Build initial CharacterState with computed AbilityPlan and starting skills."""
    ancestry_fixed, ancestry_free, ancestry_flaws = get_ancestry_boosts(ancestry_name)
    bg_options, bg_free = get_background_boosts(background_name)
    class_key = get_class_key_ability(class_name)

    ability_plan = compute_ability_plan(
        ancestry_fixed=ancestry_fixed,
        ancestry_free_count=ancestry_free,
        ancestry_flaws=ancestry_flaws,
        background_options=bg_options,
        background_free_count=bg_free,
        class_key_abilities=class_key,
        priority_order=ability_priority,
        character_level=character_level,
    )

    starting_skills = compute_starting_skills(
        class_name, background_name, ability_plan, skill_priority,
    )

    return CharacterState(
        class_name=class_name,
        ancestry_name=ancestry_name,
        character_level=character_level,
        ability_plan=ability_plan,
        skills=starting_skills,
    )


def compute_starting_skills(
    class_name: str,
    background_name: str,
    ability_plan: AbilityPlan,
    skill_priority: list[str],
) -> dict[str, str]:
    """Compute trained skills at character creation."""
    skills: dict[str, str] = {}

    # Class fixed grants
    class_ts = get_class_trained_skills(class_name)
    for s in class_ts["fixed"]:
        skills[s.lower()] = "trained"

    # Class custom lore
    if class_ts["custom"]:
        skills[class_ts["custom"].lower()] = "trained"

    # Background grants
    bg_skills = get_background_trained_skills(background_name)
    for s in bg_skills:
        skills[s.lower()] = "trained"

    # Free skill training slots from class + Int modifier
    int_score = ability_plan.at_level(1).get("int", 10)
    int_modifier = max(0, (int_score - 10) // 2)
    free_slots = class_ts["additional"] + int_modifier

    for s in skill_priority:
        if free_slots <= 0:
            break
        s_lower = s.lower()
        if s_lower not in skills:
            skills[s_lower] = "trained"
            free_slots -= 1

    return skills


# ---------------------------------------------------------------------------
# Slot types for the progressive loop
# ---------------------------------------------------------------------------

@dataclass
class ProgressiveSlot:
    """Unified slot representation for the progressive loop."""
    slot_type: str          # "class_feat", "ancestry_feat", "general_feat", "skill_feat", "skill_increase"
    level: int
    source: str = ""        # class name, ancestry name, etc.
    slot_options: SlotOptions | None = None  # for feat slots, the decomposed options


def build_slot_sequence(options: BuildOptions, class_name: str, character_level: int) -> list[ProgressiveSlot]:
    """Build the ordered sequence of all slots to process.

    Includes feat slots from BuildOptions plus skill increase slots.
    Sorted by level, with skill increases before feat slots at the same level.
    """
    slots: list[ProgressiveSlot] = []

    # Feat slots from BuildOptions
    for so in options.slot_options:
        slots.append(ProgressiveSlot(
            slot_type=f"{so.slot.slot_type}_feat",
            level=so.slot.level,
            source=so.slot.source,
            slot_options=so,
        ))

    # Skill increase slots
    increase_levels = get_skill_increase_levels(class_name)
    for lvl in increase_levels:
        if lvl > character_level:
            break
        slots.append(ProgressiveSlot(
            slot_type="skill_increase",
            level=lvl,
        ))

    # Sort: by level, then skill increases before feat slots at same level
    def sort_key(s: ProgressiveSlot) -> tuple[int, int]:
        type_order = 0 if s.slot_type == "skill_increase" else 1
        return (s.level, type_order)

    slots.sort(key=sort_key)
    return slots


# ---------------------------------------------------------------------------
# Candidate filtering
# ---------------------------------------------------------------------------

@dataclass
class FilterResult:
    legal: list[str] = field(default_factory=list)
    rejected: dict[str, list[str]] = field(default_factory=dict)

    @property
    def total_offered(self) -> int:
        return len(self.legal) + sum(len(v) for v in self.rejected.values())

    def _reject(self, feat_name: str, reason: str) -> None:
        self.rejected.setdefault(reason, []).append(feat_name)


def filter_candidates(
    state: CharacterState,
    slot: ProgressiveSlot,
) -> FilterResult:
    """Filter feat candidates for a slot against current state.

    Returns FilterResult with legal candidates and rejection reasons.
    For skill_increase slots, returns eligible skills (no rejection tracking).
    """
    result = FilterResult()

    if slot.slot_type == "skill_increase":
        result.legal = _filter_skill_increase_candidates(state, slot.level)
        return result

    if not slot.slot_options:
        return result

    chosen_lower = {f.name.lower() for f in state.feats_chosen}
    ability_scores = state.ability_plan.at_level(slot.level)

    slot_category = slot.slot_type.replace("_feat", "")

    for opt in slot.slot_options.options:
        name_lower = opt.name.lower()

        # 0. Category mismatch (feat filed in wrong directory)
        if opt.category and opt.category != slot_category and opt.category != "":
            result._reject(opt.name, "category_mismatch")
            continue

        # 1. Duplicate check
        if name_lower not in _REPEATABLE_FEATS and name_lower in chosen_lower:
            result._reject(opt.name, "duplicate")
            continue

        # 2-5. Prereq checks (feat prereqs, dedication ordering, ability scores, skills)
        passed, reason = _check_feat_prereqs(opt.name, state, ability_scores)
        if not passed:
            result._reject(opt.name, reason)
            continue

        result.legal.append(opt.name)

    return result


def _filter_skill_increase_candidates(state: CharacterState, level: int) -> list[str]:
    """Get skills eligible for rank-up at this level."""
    eligible = []
    for skill, rank in state.skills.items():
        rank_int = _RANK_ORDER.get(rank, 0)
        if rank_int >= 4:
            continue
        next_rank = rank_int + 1
        # Expert requires level 3+, master requires level 7+, legendary requires level 15+
        min_level_for_rank = {2: 3, 3: 7, 4: 15}
        if level < min_level_for_rank.get(next_rank, 0):
            continue
        eligible.append(skill)
    return sorted(eligible)


def _check_feat_prereqs(
    feat_name: str, state: CharacterState, ability_scores: dict[str, int],
) -> tuple[bool, str]:
    """Check if a feat's prerequisites are satisfiable given current state.

    Returns (passed, reason). Reason is empty string on pass.
    """
    entry = get_feat_data(feat_name)
    if not entry:
        return True, ""

    # Check dedication ordering (archetype rules)
    traits = entry.get("system", {}).get("traits", {}).get("value", [])
    traits_lower = [t.lower() for t in traits]

    if "dedication" in traits_lower:
        if state.dedications_taken:
            last_ded = state.dedications_taken[-1]
            arch_count = state.archetype_feat_counts.get(last_ded, 0)
            if arch_count < 2:
                return False, "dedication_ordering"

    prereqs = entry.get("system", {}).get("prerequisites", {}).get("value", [])
    if not prereqs:
        return True, ""

    from validator.types import ParsedBuild
    proxy_build = ParsedBuild(
        class_name=state.class_name,
        ancestry_name=state.ancestry_name,
        character_level=state.character_level,
        ability_scores=ability_scores,
        skills=state.skills,
        feats=list(state.feats_chosen),
    )

    for p in prereqs:
        pval = p.get("value", "") if isinstance(p, dict) else str(p)
        if not pval:
            continue

        parsed = parse_prerequisites(pval)
        for prereq in parsed:
            satisfied, _reason = check_prerequisite(prereq, proxy_build)
            if not satisfied:
                return False, f"prereq_{prereq.type}"

    return True, ""


# ---------------------------------------------------------------------------
# State update
# ---------------------------------------------------------------------------

def update_state(state: CharacterState, feat_name: str, slot: ProgressiveSlot) -> None:
    """Apply a feat or skill-increase choice to the running state (mutates in place)."""
    if slot.slot_type == "skill_increase":
        current_rank = _RANK_ORDER.get(state.skills.get(feat_name, "untrained"), 0)
        next_rank = _RANK_BY_INT.get(current_rank + 1, "trained")
        state.skills[feat_name] = next_rank
        return

    slot_type = slot.slot_type.replace("_feat", "")
    feat_choice = ParsedFeatChoice(
        name=feat_name,
        slot_type=slot_type,
        character_level=slot.level,
    )
    state.feats_chosen.append(feat_choice)

    # Check if this is a dedication or archetype feat
    entry = get_feat_data(feat_name)
    if entry:
        traits = entry.get("system", {}).get("traits", {}).get("value", [])
        traits_lower = [t.lower() for t in traits]

        if "dedication" in traits_lower:
            ded_name = feat_name.lower().replace(" dedication", "")
            state.dedications_taken.append(ded_name)
            state.archetype_feat_counts.setdefault(ded_name, 0)
        elif "archetype" in traits_lower and state.dedications_taken:
            last_ded = state.dedications_taken[-1]
            state.archetype_feat_counts[last_ded] = state.archetype_feat_counts.get(last_ded, 0) + 1


# ---------------------------------------------------------------------------
# Dedication locking
# ---------------------------------------------------------------------------

def plan_dedication_slots(
    options: BuildOptions,
    dedications: list[str],
    ability_plan: AbilityPlan,
) -> dict[str, str] | str:
    """Pre-assign dedication feats to class feat slots deterministically.

    Returns locked_slots dict on success, or an error message string on failure.

    Known limitation: checks ability score prereqs but NOT feat prereqs.
    E.g., Medic Dedication requires Battle Medicine — the scheduler locks the
    slot without ensuring Battle Medicine is taken earlier. This is path-seeking
    territory (backward dependency resolution). Benchmark failures from this gap
    inform the path-seeking decision.
    """
    if not dedications:
        return {}

    # Get class feat slot levels
    slot_levels = get_feat_slot_levels(options.spec.class_name)
    class_feat_levels = [l for l in slot_levels["class"] if l <= options.spec.character_level]

    if not class_feat_levels:
        return "No class feat slots available for dedications"

    locked: dict[str, str] = {}
    used_slots: set[int] = set()

    from query.static_reader import list_archetype_feats

    for ded_idx, ded_name in enumerate(dedications):
        # Find the dedication feat
        ded_feats = list_archetype_feats(ded_name, options.spec.character_level)
        ded_feat = None
        for f in ded_feats:
            if "dedication" in [t.lower() for t in f.traits]:
                ded_feat = f
                break

        if not ded_feat:
            return f"Dedication feat not found for '{ded_name}'"

        # Check ability score prereqs
        if ded_feat.prerequisites:
            parsed_prereqs = parse_prerequisites(ded_feat.prerequisites)
            for prereq in parsed_prereqs:
                if prereq.type == "ability_score":
                    parts = prereq.value.split(":")
                    if len(parts) == 2:
                        ability, required = parts[0], int(parts[1])
                        # Check across all levels where this dedication could be placed
                        reachable = False
                        for lvl in class_feat_levels:
                            if lvl in used_slots:
                                continue
                            if ded_feat.level <= lvl:
                                scores = ability_plan.at_level(lvl)
                                if scores.get(ability, 0) >= required:
                                    reachable = True
                                    break
                        if not reachable:
                            return (
                                f"Dedication '{ded_feat.name}' requires {prereq.raw} "
                                f"but AbilityPlan cannot reach it at any available slot"
                            )

        # For dedications after the first, need 2 archetype feats from prior dedication
        if ded_idx > 0:
            available_for_arch = [l for l in class_feat_levels
                                  if l not in used_slots and l > min(used_slots)]
            if len(available_for_arch) < 3:  # 2 archetype feats + this dedication
                return (
                    f"Not enough class feat slots for dual dedication: "
                    f"need 2 archetype feats from '{dedications[ded_idx-1]}' "
                    f"before '{ded_name}' dedication, but only {len(available_for_arch)} slots available"
                )
            # Lock 2 archetype feat slots (don't assign specific feats — LLM picks from filtered archetype feats)
            for arch_slot_level in available_for_arch[:2]:
                locked[f"{arch_slot_level}_class_feat"] = f"__archetype_from_{dedications[ded_idx-1]}"
                used_slots.add(arch_slot_level)

        # Assign this dedication to the earliest eligible slot
        assigned = False
        for lvl in class_feat_levels:
            if lvl in used_slots:
                continue
            if ded_feat.level <= lvl:
                locked[f"{lvl}_class_feat"] = ded_feat.name
                used_slots.add(lvl)
                assigned = True
                break

        if not assigned:
            return f"No eligible class feat slot for '{ded_feat.name}' (requires level {ded_feat.level}+)"

    return locked


# ---------------------------------------------------------------------------
# Progressive build controller
# ---------------------------------------------------------------------------

@dataclass
class SlotTrace:
    slot_type: str
    level: int
    candidates_offered: int
    candidates_after_filter: int
    choice: str
    auto_assigned: bool
    locked: bool
    llm_time: float
    rejections: dict[str, int] = field(default_factory=dict)


def progressive_build(
    options: BuildOptions,
    request: str,
    model: str,
    character_level: int,
    class_name: str,
    ancestry_name: str,
    dedications: list[str],
    background_name: str = "",
    temperature: float = 0.5,
    ollama_options: dict | None = None,
    verbose: bool = True,
) -> dict:
    """Run the progressive generation pipeline.

    1. Upfront LLM priority call (ability + skill priorities)
    2. Compute AbilityPlan and starting skills deterministically
    3. Lock dedication slots
    4. Progressive loop: fill each slot with filtered candidates
    5. Final assembly: equipment + notes via LLM
    6. Full validation
    """
    from orchestrator.pipeline import _call_ollama, _unload_all_models, THINKING_MODELS
    from orchestrator.prompt_builder import (
        build_priority_prompt, build_priority_schema, _PRIORITY_SYSTEM_PROMPT,
        build_slot_prompt, build_slot_schema, _SLOT_SYSTEM_PROMPT,
        build_skill_increase_prompt,
        build_state_summary,
        build_assembly_prompt, build_assembly_schema, _ASSEMBLY_SYSTEM_PROMPT,
    )
    from validator.engine import BuildValidator

    timings: dict[str, float] = {}
    all_usages: list[dict] = []
    trace: list[SlotTrace] = []

    # ---- Step 1: Upfront priority call ----
    if verbose:
        print("[progressive] Step 1: Upfront priority call...")

    class_ts = get_class_trained_skills(class_name)
    class_key = get_class_key_ability(class_name)
    ancestry_fixed, ancestry_free, ancestry_flaws = get_ancestry_boosts(ancestry_name)
    # Ask for generous skill priorities — the actual count depends on Int after AbilityPlan
    # is computed. Over-requesting is harmless (compute_starting_skills uses only what it needs).
    max_int_mod = 4  # Int 18 = +4, theoretical max at L1
    free_skill_slots = class_ts["additional"] + max_int_mod

    # Extract dedication ability requirements (both for prompt and deterministic enforcement)
    dedication_requirements = []  # display strings for prompt
    required_abilities: set[str] = set()  # ability names that MUST be prioritized
    if dedications:
        from query.static_reader import list_archetype_feats
        for ded_name in dedications:
            ded_feats = list_archetype_feats(ded_name, character_level)
            for f in ded_feats:
                if "dedication" in [t.lower() for t in f.traits] and f.prerequisites:
                    parsed = parse_prerequisites(f.prerequisites)
                    for p in parsed:
                        if p.type == "ability_score":
                            dedication_requirements.append(f"{f.name} requires {p.raw}")
                            ability = p.value.split(":")[0]
                            if ability in _ABILITIES:
                                required_abilities.add(ability)

    # Get available backgrounds and heritages for the priority call
    # Only include background/heritage in the priority call if not pre-specified
    from query.static_reader import list_backgrounds, list_heritages
    pick_background = not background_name
    pick_heritage = True  # heritage is never pre-specified currently
    available_backgrounds = list_backgrounds() if pick_background else None
    available_heritages = (list_heritages(ancestry_name) if ancestry_name else []) if pick_heritage else None

    priority_prompt = build_priority_prompt(
        request, class_name, ancestry_name, character_level,
        class_key, free_skill_slots, class_ts["fixed"],
        dedication_requirements=dedication_requirements or None,
        available_backgrounds=available_backgrounds,
        available_heritages=available_heritages or None,
    )
    priority_schema = build_priority_schema(
        free_skill_slots,
        available_backgrounds=available_backgrounds,
        available_heritages=available_heritages or None,
    )

    priority_raw, priority_time, priority_usage = _call_ollama(
        model, priority_prompt, _PRIORITY_SYSTEM_PROMPT,
        temperature=0.7, response_schema=priority_schema,
        max_tokens=512, ollama_options=ollama_options,
    )
    timings["priority"] = priority_time
    all_usages.append(priority_usage)

    try:
        priority_json = json.loads(priority_raw)
    except json.JSONDecodeError:
        if verbose:
            print(f"[progressive] Priority call JSON parse failed: {priority_raw[:200]}")
        _unload_all_models()
        return {"error": "Priority call JSON parse failed", "timings": timings}

    ability_priority = priority_json.get("ability_priority", [])
    skill_priority = priority_json.get("skill_priority", [])

    # Extract background and heritage from priority call (if not pre-specified)
    if not background_name:
        background_name = priority_json.get("background", "")
        if background_name and available_backgrounds and background_name not in available_backgrounds:
            if verbose:
                print(f"[progressive] Invalid background '{background_name}', clearing")
            background_name = ""
    heritage_name = priority_json.get("heritage", "")
    if heritage_name and available_heritages and heritage_name not in available_heritages:
        if verbose:
            print(f"[progressive] Invalid heritage '{heritage_name}', clearing")
        heritage_name = ""

    # Validate priority output
    if not ability_priority or len(set(ability_priority)) != 6 or set(ability_priority) != set(_ABILITIES):
        if verbose:
            print(f"[progressive] Invalid ability_priority: {ability_priority}, using fallback")
        ability_priority = ["cha", "str", "con", "dex", "wis", "int"]

    # Deterministic enforcement: required abilities must be in top positions
    if required_abilities:
        enforced = [a for a in ability_priority if a in required_abilities]
        rest = [a for a in ability_priority if a not in required_abilities]
        if enforced != ability_priority[:len(enforced)]:
            ability_priority = enforced + rest
            if verbose:
                print(f"[progressive] Reordered priority to ensure {required_abilities} are top-ranked")

    if verbose:
        print(f"[progressive] Ability priority: {ability_priority}")
        print(f"[progressive] Skill priority: {skill_priority}")
        print(f"[progressive] Background: {background_name or '(none)'}")
        print(f"[progressive] Heritage: {heritage_name or '(none)'}")

    # ---- Step 2: Compute AbilityPlan + starting skills ----
    if verbose:
        print("[progressive] Step 2: Computing AbilityPlan and starting skills...")

    bg_options, bg_free = get_background_boosts(background_name) if background_name else ([], 0)

    ability_plan = compute_ability_plan(
        ancestry_fixed=ancestry_fixed,
        ancestry_free_count=ancestry_free,
        ancestry_flaws=ancestry_flaws,
        background_options=bg_options,
        background_free_count=bg_free,
        class_key_abilities=class_key,
        priority_order=ability_priority,
        character_level=character_level,
    )
    starting_skills = compute_starting_skills(
        class_name, background_name, ability_plan, skill_priority,
    )

    state = CharacterState(
        class_name=class_name,
        ancestry_name=ancestry_name,
        character_level=character_level,
        ability_plan=ability_plan,
        skills=starting_skills,
    )

    if verbose:
        print(f"[progressive] Ability scores at L1: {state.ability_plan.at_level(1)}")
        print(f"[progressive] Starting skills: {state.skills}")

    # ---- Step 3: Lock dedication slots ----
    if dedications:
        if verbose:
            print(f"[progressive] Step 3: Locking dedication slots for {dedications}...")
        locked = plan_dedication_slots(options, dedications, state.ability_plan)
        if isinstance(locked, str):
            if verbose:
                print(f"[progressive] Dedication locking failed: {locked}")
            _unload_all_models()
            return {"error": f"Dedication infeasible: {locked}", "timings": timings}
        state.locked_slots = locked
        if verbose:
            for k, v in sorted(locked.items()):
                print(f"[progressive]   {k}: {v}")

    # ---- Step 4: Progressive loop ----
    if verbose:
        print("[progressive] Step 4: Progressive slot-by-slot generation...")

    slots = build_slot_sequence(options, class_name, character_level)
    slot_stats = {
        "total": len(slots), "locked": 0, "auto_assigned": 0, "llm_decided": 0,
        "skill_increase": 0,
        "by_type": {},
    }

    for slot in slots:
        slot_key = f"{slot.level}_{slot.slot_type}"
        type_stats = slot_stats["by_type"].setdefault(slot.slot_type, {
            "total": 0, "locked": 0, "auto": 0, "llm": 0,
        })
        type_stats["total"] += 1

        # --- Locked slots ---
        if slot_key in state.locked_slots:
            locked_value = state.locked_slots[slot_key]
            t0 = time.perf_counter()

            if locked_value.startswith("__archetype_from_"):
                ded_name = locked_value.replace("__archetype_from_", "")
                result = filter_candidates(state, slot)
                # Filter to non-dedication archetype feats from this specific dedication
                from query.static_reader import list_archetype_feats as _list_arch
                valid_arch_names = {
                    f.name.lower() for f in _list_arch(ded_name, character_level)
                    if "dedication" not in [t.lower() for t in f.traits]
                }
                arch_candidates = [c for c in result.legal if c.lower() in valid_arch_names]

                if not arch_candidates:
                    if verbose:
                        print(f"  L{slot.level} {slot.slot_type}: LOCKED archetype from {ded_name} — no candidates!")
                    trace.append(SlotTrace(
                        slot.slot_type, slot.level, result.total_offered, 0,
                        "", False, True, 0,
                    ))
                    slot_stats["locked"] += 1
                    type_stats["locked"] += 1
                    continue

                if len(arch_candidates) == 1:
                    choice = arch_candidates[0]
                    update_state(state, choice, slot)
                    if verbose:
                        print(f"  L{slot.level} {slot.slot_type}: LOCKED archetype → {choice} (only option)")
                    trace.append(SlotTrace(
                        slot.slot_type, slot.level, result.total_offered, len(arch_candidates),
                        choice, True, True, 0,
                    ))
                    slot_stats["locked"] += 1
                    type_stats["locked"] += 1
                    continue

                # LLM picks from filtered archetype feats
                prompt = build_slot_prompt(
                    request, f"archetype_{ded_name}", slot.level,
                    arch_candidates, build_state_summary(state),
                )
                schema = build_slot_schema(arch_candidates)
                raw, call_time, usage = _call_ollama(
                    model, prompt, _SLOT_SYSTEM_PROMPT, temperature,
                    response_schema=schema, max_tokens=256,
                    ollama_options=ollama_options,
                )
                timings[f"slot_{slot_key}"] = call_time
                all_usages.append(usage)
                try:
                    choice = json.loads(raw).get("choice", arch_candidates[0])
                except json.JSONDecodeError:
                    choice = arch_candidates[0]
                update_state(state, choice, slot)
                if verbose:
                    print(f"  L{slot.level} {slot.slot_type}: LOCKED archetype → {choice} (LLM from {len(arch_candidates)})")
                trace.append(SlotTrace(
                    slot.slot_type, slot.level, result.total_offered, len(arch_candidates),
                    choice, False, True, call_time,
                ))
                slot_stats["locked"] += 1
                type_stats["locked"] += 1

            else:
                # Directly locked feat (e.g., Champion Dedication)
                update_state(state, locked_value, slot)
                if verbose:
                    print(f"  L{slot.level} {slot.slot_type}: LOCKED → {locked_value}")
                trace.append(SlotTrace(
                    slot.slot_type, slot.level, 1, 1,
                    locked_value, True, True, 0,
                ))
                slot_stats["locked"] += 1
                type_stats["locked"] += 1

            continue

        # --- Non-locked slots ---
        result = filter_candidates(state, slot)
        candidates = result.legal
        rejections = {k: len(v) for k, v in result.rejected.items()}

        if slot.slot_type == "skill_increase":
            slot_stats["skill_increase"] += 1
            if not candidates:
                if verbose:
                    print(f"  L{slot.level} {slot.slot_type}: no eligible skills")
                trace.append(SlotTrace(slot.slot_type, slot.level, 0, 0, "", False, False, 0))
                continue

            if len(candidates) == 1:
                update_state(state, candidates[0], slot)
                if verbose:
                    print(f"  L{slot.level} {slot.slot_type}: AUTO → {candidates[0]}")
                trace.append(SlotTrace(
                    slot.slot_type, slot.level, len(candidates), 1,
                    candidates[0], True, False, 0,
                ))
                type_stats["auto"] += 1
                slot_stats["auto_assigned"] += 1
                continue

            prompt = build_skill_increase_prompt(
                request, slot.level, candidates, build_state_summary(state),
            )
            schema = build_slot_schema(candidates)
            raw, call_time, usage = _call_ollama(
                model, prompt, _SLOT_SYSTEM_PROMPT, temperature,
                response_schema=schema, max_tokens=256,
                ollama_options=ollama_options,
            )
            timings[f"slot_{slot_key}"] = call_time
            all_usages.append(usage)
            try:
                choice = json.loads(raw).get("choice", candidates[0])
            except json.JSONDecodeError:
                choice = candidates[0]
            update_state(state, choice, slot)
            if verbose:
                print(f"  L{slot.level} {slot.slot_type}: LLM → {choice} (from {len(candidates)})")
            trace.append(SlotTrace(
                slot.slot_type, slot.level, len(candidates), len(candidates),
                choice, False, False, call_time,
            ))
            type_stats["llm"] += 1
            slot_stats["llm_decided"] += 1
            continue

        # --- Feat slots ---
        offered = result.total_offered

        if not candidates:
            if verbose:
                print(f"  L{slot.level} {slot.slot_type}: NO CANDIDATES (from {offered}, rejected: {rejections})")
            trace.append(SlotTrace(
                slot.slot_type, slot.level, offered, 0, "", False, False, 0,
                rejections=rejections,
            ))
            continue

        if len(candidates) == 1:
            update_state(state, candidates[0], slot)
            if verbose:
                print(f"  L{slot.level} {slot.slot_type}: AUTO → {candidates[0]} (from {offered})")
            trace.append(SlotTrace(
                slot.slot_type, slot.level, offered, 1,
                candidates[0], True, False, 0,
                rejections=rejections,
            ))
            slot_stats["auto_assigned"] += 1
            type_stats["auto"] += 1
            continue

        prompt = build_slot_prompt(
            request, slot.slot_type, slot.level,
            candidates, build_state_summary(state),
        )
        schema = build_slot_schema(candidates)
        raw, call_time, usage = _call_ollama(
            model, prompt, _SLOT_SYSTEM_PROMPT, temperature,
            response_schema=schema, max_tokens=256,
            ollama_options=ollama_options,
        )
        timings[f"slot_{slot_key}"] = call_time
        all_usages.append(usage)

        try:
            choice = json.loads(raw).get("choice", candidates[0])
        except json.JSONDecodeError:
            choice = candidates[0]

        if choice not in candidates:
            choice = candidates[0]

        update_state(state, choice, slot)
        if verbose:
            print(f"  L{slot.level} {slot.slot_type}: LLM → {choice} (from {len(candidates)}/{offered})")
        trace.append(SlotTrace(
            slot.slot_type, slot.level, offered, len(candidates),
            choice, False, False, call_time,
            rejections=rejections,
        ))
        slot_stats["llm_decided"] += 1
        type_stats["llm"] += 1

    # ---- Step 5: Final assembly (equipment + notes) ----
    if verbose:
        print("[progressive] Step 5: Final assembly (equipment + notes)...")

    _unload_all_models()

    assembly_summary = build_state_summary(state)
    assembly_summary += f"\nAbility scores: {state.ability_plan.at_level(character_level)}"
    assembly_prompt = build_assembly_prompt(request, assembly_summary)
    assembly_schema = build_assembly_schema()

    assembly_raw, assembly_time, assembly_usage = _call_ollama(
        model, assembly_prompt, _ASSEMBLY_SYSTEM_PROMPT,
        temperature=0.7, response_schema=assembly_schema,
        max_tokens=512, ollama_options=ollama_options,
    )
    timings["assembly"] = assembly_time
    all_usages.append(assembly_usage)

    equipment = []
    notes = ""
    try:
        assembly_json = json.loads(assembly_raw)
        equipment = assembly_json.get("equipment", [])
        notes = assembly_json.get("notes", "")
    except json.JSONDecodeError:
        if verbose:
            print("[progressive] Assembly JSON parse failed, skipping equipment/notes")

    # ---- Step 6: Build final JSON and validate ----
    if verbose:
        print("[progressive] Step 6: Final validation...")

    build_json = {
        "class": class_name,
        "ancestry": ancestry_name,
        "heritage": heritage_name,
        "background": background_name,
        "level": character_level,
        "ability_scores": state.ability_plan.at_level(character_level),
        "skills": state.skills,
        "levels": {},
        "equipment": equipment,
        "notes": notes,
    }

    # Reconstruct levels dict from feats_chosen
    for feat in state.feats_chosen:
        level_str = str(feat.character_level)
        if level_str not in build_json["levels"]:
            build_json["levels"][level_str] = {}
        key = f"{feat.slot_type}_feat"
        build_json["levels"][level_str][key] = feat.name

    # Verify fixed-value adherence (pipeline bugs, not LLM failures)
    adherence_errors = []
    if build_json["class"] != class_name:
        adherence_errors.append(f"Class drift: specified '{class_name}', got '{build_json['class']}'")
    if build_json["ancestry"] != ancestry_name:
        adherence_errors.append(f"Ancestry drift: specified '{ancestry_name}', got '{build_json['ancestry']}'")
    if background_name and build_json["background"] != background_name:
        adherence_errors.append(f"Background drift: specified '{background_name}', got '{build_json['background']}'")
    if build_json["level"] != character_level:
        adherence_errors.append(f"Level drift: specified {character_level}, got {build_json['level']}")
    for ded in dedications:
        ded_lower = f"{ded} dedication".lower()
        if not any(f.name.lower() == ded_lower for f in state.feats_chosen):
            adherence_errors.append(f"Missing dedication: '{ded}' specified but not in build")
    if adherence_errors and verbose:
        print(f"[progressive] INPUT ADHERENCE ERRORS (pipeline bugs):")
        for ae in adherence_errors:
            print(f"  BUG: {ae}")

    validator = BuildValidator()
    validation = validator.validate_json(
        build_json,
        expected_class=class_name,
        expected_ancestry=ancestry_name,
        expected_level=character_level,
    )

    if verbose:
        print(f"[progressive] Validation: {validation.error_count} errors, {len(validation.warnings)} warnings")
        for e in validation.errors:
            print(f"  ERROR: {e.message}")

    # ---- Aggregate results ----
    token_totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for u in all_usages:
        for k in token_totals:
            token_totals[k] += u.get(k, 0)

    return {
        "build_text": json.dumps(build_json, indent=2),
        "build_json": build_json,
        "validation": {
            "is_valid": validation.is_valid,
            "errors": [{"rule": e.rule, "message": e.message} for e in validation.errors],
            "warnings": [{"rule": w.rule, "message": w.message} for w in validation.warnings],
            "verified_feats": validation.verified_feats,
        },
        "attempts": 1,
        "timings": timings,
        "tokens": token_totals,
        "trace": [
            {
                "slot": f"{t.slot_type}_{t.level}",
                "candidates_offered": t.candidates_offered,
                "candidates_after_filter": t.candidates_after_filter,
                "choice": t.choice,
                "auto_assigned": t.auto_assigned,
                "locked": t.locked,
                "llm_time": t.llm_time,
                "rejections": t.rejections,
            }
            for t in trace
        ],
        "slot_stats": slot_stats,
        "ability_plan": {
            "priority": ability_priority,
            "scores_by_level": state.ability_plan.scores_by_level,
        },
        "skill_priority": skill_priority,
        "adherence_errors": adherence_errors,
    }
