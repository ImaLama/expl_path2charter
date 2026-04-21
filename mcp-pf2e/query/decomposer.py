"""Decompose a character build request into exhaustive feat option lists."""

from .types import BuildSpec, BuildOptions, FeatSlot, SlotOptions
from .static_reader import (
    get_feat_slot_levels,
    list_class_feats,
    list_ancestry_feats,
    list_general_feats,
    list_skill_feats,
    list_archetype_feats,
)


def decompose_build(spec: BuildSpec) -> BuildOptions:
    """Given a BuildSpec, enumerate all valid feat options for every slot.

    For each feat slot type (class, ancestry, general, skill), looks up which
    character levels grant a slot from the class JSON, then lists all feats
    available at or below that level.

    For archetype dedications, adds archetype feats as additional options
    for class feat slots.
    """
    slot_levels = get_feat_slot_levels(spec.class_name)
    slot_options = []

    # Pre-fetch archetype feats if dedications are specified
    archetype_feats_by_max_level: dict[int, list] = {}
    for dedication in spec.dedications:
        for lvl in slot_levels["class"]:
            if lvl <= spec.character_level and lvl not in archetype_feats_by_max_level:
                archetype_feats_by_max_level[lvl] = []
        for dedication_name in spec.dedications:
            for lvl in archetype_feats_by_max_level:
                feats = list_archetype_feats(dedication_name, lvl)
                archetype_feats_by_max_level.setdefault(lvl, [])
                for f in feats:
                    if f not in archetype_feats_by_max_level[lvl]:
                        archetype_feats_by_max_level[lvl].append(f)
        break  # Only need one pass through the outer loop

    # Class feat slots
    for lvl in slot_levels["class"]:
        if lvl > spec.character_level:
            break
        slot = FeatSlot(slot_type="class", level=lvl, source=spec.class_name)
        options = list_class_feats(spec.class_name, lvl)
        # Class feat slots can also be used for archetype feats
        if spec.dedications:
            arch_opts = archetype_feats_by_max_level.get(lvl, [])
            seen_names = {o.name for o in options}
            for af in arch_opts:
                if af.name not in seen_names:
                    options.append(af)
                    seen_names.add(af.name)
        slot_options.append(SlotOptions(slot=slot, options=sorted(options, key=lambda f: (f.level, f.name))))

    # Ancestry feat slots
    if spec.ancestry_name:
        for lvl in slot_levels["ancestry"]:
            if lvl > spec.character_level:
                break
            slot = FeatSlot(slot_type="ancestry", level=lvl, source=spec.ancestry_name)
            options = list_ancestry_feats(spec.ancestry_name, lvl)
            slot_options.append(SlotOptions(slot=slot, options=sorted(options, key=lambda f: (f.level, f.name))))

    # General feat slots
    for lvl in slot_levels["general"]:
        if lvl > spec.character_level:
            break
        slot = FeatSlot(slot_type="general", level=lvl, source="")
        options = list_general_feats(lvl)
        slot_options.append(SlotOptions(slot=slot, options=sorted(options, key=lambda f: (f.level, f.name))))

    # Skill feat slots
    for lvl in slot_levels["skill"]:
        if lvl > spec.character_level:
            break
        slot = FeatSlot(slot_type="skill", level=lvl, source="")
        options = list_skill_feats(lvl)
        slot_options.append(SlotOptions(slot=slot, options=sorted(options, key=lambda f: (f.level, f.name))))

    return BuildOptions(spec=spec, slot_options=slot_options)


def get_build_options(
    class_name: str,
    character_level: int,
    ancestry_name: str = "",
    dedications: list[str] | None = None,
) -> BuildOptions:
    """Convenience function: build a spec and decompose it."""
    spec = BuildSpec(
        character_level=character_level,
        class_name=class_name,
        ancestry_name=ancestry_name,
        dedications=dedications or [],
    )
    return decompose_build(spec)
