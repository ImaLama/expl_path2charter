"""
PF2e Challenge Pack — Pathfinder 2e character generation evaluation.

Tests LLMs on their ability to generate mechanically valid, complete, and
creative Pathfinder 2nd Edition character builds across varying complexity.
"""

from llm_eval.types import ChallengePack, Prompt, Rubric, ScoreCriterion, AutoScorer

from .auto_scorer import PF2eAutoScorer


class PF2ePack(ChallengePack):

    @property
    def name(self) -> str:
        return "pf2e"

    @property
    def description(self) -> str:
        return "Pathfinder 2e character generation"

    def get_system_prompt(self) -> str | None:
        return (
            "You are an expert Pathfinder 2nd Edition character builder with "
            "deep knowledge of all official PF2e rules, classes, ancestries, "
            "feats, and equipment from the Core Rulebook, Advanced Player's "
            "Guide, Guns & Gears, and other official sourcebooks. Generate "
            "complete, mechanically valid character builds. Be precise about "
            "rule sources. Flag any uncertainty. Do NOT invent feats, features, "
            "or rules that don't exist in official PF2e content."
        )

    def get_prompts(self) -> list[Prompt]:
        return [
            Prompt(
                key="elf-wizard-simple",
                label="Level 3 Elf Wizard (straightforward, common class)",
                difficulty="easy",
                content=(
                    "Generate a complete, mechanically valid PF2e character:\n\n"
                    "**Character Concept:** A level 3 Elf Wizard specializing in evocation magic.\n\n"
                    "**Requirements:**\n"
                    "1. Ancestry: Elf, with heritage and ancestry feat at level 1\n"
                    "2. Background with skill training and feat\n"
                    "3. Class: Wizard with arcane school (Evocation), class feats at levels 1 and 2\n"
                    "4. Complete ability scores (standard boost system)\n"
                    "5. Prepared spell list for the day (cantrips + leveled spells appropriate for level 3)\n"
                    "6. Skill proficiencies, skill feat at level 2, general feat at level 3\n"
                    "7. Equipment loadout (level 3 budget: 25 gp)\n"
                    "8. Brief personality note\n\n"
                    "Be precise about mechanical sources. Flag any uncertainty."
                ),
            ),
            Prompt(
                key="vague-concept",
                label="Vague concept (tests creative interpretation)",
                difficulty="medium",
                content=(
                    "I want a level 5 character that is sneaky, good with poisons, "
                    "and has some connection to nature. Maybe a bit feral. I don't care "
                    "about specific class or ancestry — surprise me with something that "
                    "fits this vibe while being mechanically strong.\n\n"
                    "Build the full character sheet with all mechanical details (ability "
                    "scores, feats, skills, equipment for 160 gp). Flag any rule uncertainties."
                ),
            ),
            Prompt(
                key="goblin-inventor",
                label="Level 5 Goblin Inventor (complex, mechanical focus)",
                difficulty="hard",
                content=(
                    "Generate a complete, mechanically valid PF2e character at level 5 "
                    "using the following constraints:\n\n"
                    "**Character Concept:** A cunning Goblin Inventor (from Guns & Gears) "
                    "who builds bizarre contraptions and fights with a modified weapon innovation.\n\n"
                    "**Requirements:**\n"
                    "1. Full ancestry breakdown: heritage, ancestry feats (levels 1, 5)\n"
                    "2. Background with skill training and feat\n"
                    "3. Class features: innovation choice (weapon), initial and level-up class feats (1, 2, 4)\n"
                    "4. Complete ability scores using the standard boost system (4 free boosts at level 1, "
                    "plus ancestry/background/class, then level 5 boosts)\n"
                    "5. Skill proficiencies and skill feats (levels 1, 2, 4)\n"
                    "6. General feats (levels 3, 5)\n"
                    "7. Equipment loadout appropriate for level 5 (with 160 gp budget)\n"
                    "8. A weapon innovation with the modification choices available at this level\n"
                    "9. A brief personality/backstory paragraph\n\n"
                    "**Format:** Use clear headers and be precise about the mechanical sources. "
                    "Flag if anything is uncertain or if you're unsure about a specific rule interaction. "
                    "Do NOT invent feats, features, or rules that don't exist in official PF2e content."
                ),
            ),
            Prompt(
                key="multiclass-tank",
                label="Level 8 Champion/Bard multiclass (hard, tests deep rules knowledge)",
                difficulty="hard",
                content=(
                    "Generate a complete, mechanically valid PF2e character:\n\n"
                    "**Character Concept:** A level 8 Human Champion (Paladin cause) who has taken the "
                    "Bard multiclass archetype dedication to gain inspire courage and some healing support.\n\n"
                    "**Requirements:**\n"
                    "1. Full ancestry + heritage + ancestry feats (1, 5)\n"
                    "2. Background\n"
                    "3. Champion class features and class feats, plus Bard Dedication and follow-up archetype feats\n"
                    "4. Complete ability scores through level 8 (including all boost stages)\n"
                    "5. Proficiencies in all relevant areas (weapons, armor, divine spellcasting, occult via archetype)\n"
                    "6. Spell slots and prepared/spontaneous spells from both traditions\n"
                    "7. Complete feat selection: class (1,2,4,6,8), skill (1,2,4,6,8), general (3,7), ancestry (1,5)\n"
                    "8. Equipment loadout for level 8 (355 gp budget)\n"
                    "9. Brief personality\n\n"
                    "This is a complex build — be very precise about multiclass archetype rules, "
                    "especially the dedication feat requirements and what archetype feats are available "
                    "at each level. Flag any uncertainties."
                ),
            ),
            Prompt(
                key="goblin-thaum-champion-exemplar",
                label="Level 8 Goblin Thaumaturge with Champion + Exemplar dedications (hard)",
                difficulty="hard",
                content=(
                    "Create a level 8 Goblin Thaumaturge with Champion Dedication and one level "
                    "in Exemplar Dedication. He should be wielding a weapon implement and a shield "
                    "implement.\n\n"
                    "**Requirements:**\n"
                    "1. Full ancestry breakdown: heritage, ancestry feats (levels 1, 5)\n"
                    "2. Background with skill training and feat\n"
                    "3. Class: Thaumaturge with weapon implement and shield implement\n"
                    "4. Champion Dedication archetype and any follow-up archetype feats taken at legal levels\n"
                    "5. Exemplar Dedication archetype (one level only) taken at a legal level\n"
                    "6. Make feat and skill choices that synergize with the overall build\n"
                    "7. Optimize ability scores using the standard boost system through level 8 "
                    "(including all boost stages)\n"
                    "8. Optimize skill proficiency levels for the build\n"
                    "9. Complete feat selection: class (1,2,4,6,8), skill (1,2,4,6,8), general (3,7), "
                    "ancestry (1,5) — noting which slots are used for dedication/archetype feats\n"
                    "10. Equipment loadout for level 8 (355 gp budget)\n"
                    "11. Brief personality/backstory paragraph\n\n"
                    "This is a complex multiclass build with TWO archetype dedications — be very "
                    "precise about dedication feat prerequisites, the archetype feat tax, and which "
                    "feats are available at each level. The build must comply with Pathfinder 2e "
                    "rules in all ways. Flag any uncertainties or rule interactions that need GM adjudication."
                ),
            ),
            Prompt(
                key="goblin-thaum-champion-thrower",
                label="Level 8 Goblin Thaumaturge with Champion dedication, throwing weapons (hard)",
                difficulty="hard",
                content=(
                    "For Pathfinder 2e, create a level 8 Goblin Thaumaturge with Champion Dedication. "
                    "He should be wielding a weapon implement and another implement (find one with good "
                    "synergy for this build). He should be using throwing weapons.\n\n"
                    "**Requirements:**\n"
                    "1. Full ancestry breakdown: heritage, ancestry feats (levels 1, 5)\n"
                    "2. Background with skill training and feat\n"
                    "3. Class: Thaumaturge with weapon implement plus a second implement chosen for "
                    "synergy with a throwing weapon build\n"
                    "4. Champion Dedication archetype and any follow-up archetype feats at legal levels\n"
                    "5. Make feat and skill choices that synergize with the overall throwing weapon build\n"
                    "6. Optimize ability scores using the standard boost system through level 8 "
                    "(including all boost stages)\n"
                    "7. Optimize skill proficiency levels for the build\n"
                    "8. Complete feat selection: class (1,2,4,6,8), skill (1,2,4,6,8), general (3,7), "
                    "ancestry (1,5) — noting which slots are used for the Champion Dedication\n"
                    "9. Equipment loadout for level 8 (355 gp budget) — include specific throwing weapons\n"
                    "10. Brief personality/backstory paragraph\n\n"
                    "Be very precise about dedication feat prerequisites, the archetype feat tax, "
                    "and which feats are available at each level. Explain your implement and throwing "
                    "weapon choices. The build must comply with Pathfinder 2e rules in all ways. "
                    "Flag any uncertainties."
                ),
            ),
        ]

    def get_rubric(self) -> Rubric:
        return Rubric(
            criteria=[
                ScoreCriterion(
                    key="rule_legality",
                    label="Rule Legality",
                    description=(
                        "Does the build follow PF2e rules correctly? Check for:\n"
                        "- Valid ancestry/heritage/background combinations\n"
                        "- Correct ability score math (boosts/flaws applied properly)\n"
                        "- Feats that actually exist in PF2e and are taken at legal levels\n"
                        "- Class features applied correctly for the level\n"
                        "- Proficiency progressions that match the class\n"
                        "- Multiclass/archetype rules followed (if applicable)\n"
                        "Score 1 = multiple fabricated rules/feats. Score 5 = every detail is rules-legal."
                    ),
                    weight=0.30,
                ),
                ScoreCriterion(
                    key="completeness",
                    label="Completeness",
                    description=(
                        "Are all required character elements filled in?\n"
                        "- Ability scores, HP, AC, saves, perception\n"
                        "- All feat slots filled (ancestry, class, general, skill — at correct levels)\n"
                        "- Skills with proficiency ranks\n"
                        "- Equipment with costs\n"
                        "- Spells if applicable (correct slots, valid spell list)\n"
                        "Score 1 = major sections missing. Score 5 = every slot filled, nothing left blank."
                    ),
                    weight=0.20,
                ),
                ScoreCriterion(
                    key="concept_fidelity",
                    label="Concept Fidelity",
                    description=(
                        "Does the build match what the user asked for?\n"
                        "- Ancestry/class/theme matches the request\n"
                        "- Mechanical choices support the stated concept\n"
                        "- If the prompt was vague, did the builder make a coherent interpretation?\n"
                        "Score 1 = ignores the request. Score 5 = nails the concept perfectly."
                    ),
                    weight=0.20,
                ),
                ScoreCriterion(
                    key="mechanical_cohesion",
                    label="Mechanical Cohesion",
                    description=(
                        "Do the choices synergize into an effective character?\n"
                        "- Ability scores support the class/build\n"
                        "- Feats complement each other and the playstyle\n"
                        "- Equipment choices make sense for the build\n"
                        "- The character would actually function well in play\n"
                        "Score 1 = random/contradictory choices. Score 5 = tight, optimized synergy."
                    ),
                    weight=0.15,
                ),
                ScoreCriterion(
                    key="creativity",
                    label="Creativity & Presentation",
                    description=(
                        "Is the build interesting and well-presented?\n"
                        "- Are choices beyond the most obvious/generic defaults?\n"
                        "- Is the backstory/personality meaningful (not boilerplate)?\n"
                        "- Is the formatting clear and easy to follow?\n"
                        "- Does it show genuine PF2e system knowledge?\n"
                        "Score 1 = bland/cookie-cutter. Score 5 = inspired and expertly presented."
                    ),
                    weight=0.15,
                ),
            ],
            judge_preamble=(
                "You are an expert Pathfinder 2nd Edition rules judge. Evaluate this "
                "character build for mechanical accuracy and quality. Pay special attention "
                "to fabricated content — feats, features, spells, or rules that do not exist "
                "in official PF2e sourcebooks. List any fabricated content in a "
                "'fabricated_content' field in your response."
            ),
            output_schema={
                "type": "object",
                "properties": {
                    "rule_legality": {
                        "type": "object",
                        "properties": {
                            "score": {"type": "integer", "minimum": 1, "maximum": 5},
                            "issues": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                    "completeness": {
                        "type": "object",
                        "properties": {
                            "score": {"type": "integer", "minimum": 1, "maximum": 5},
                            "missing": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                    "concept_fidelity": {
                        "type": "object",
                        "properties": {
                            "score": {"type": "integer", "minimum": 1, "maximum": 5},
                            "notes": {"type": "string"},
                        },
                    },
                    "mechanical_cohesion": {
                        "type": "object",
                        "properties": {
                            "score": {"type": "integer", "minimum": 1, "maximum": 5},
                            "notes": {"type": "string"},
                        },
                    },
                    "creativity": {
                        "type": "object",
                        "properties": {
                            "score": {"type": "integer", "minimum": 1, "maximum": 5},
                            "notes": {"type": "string"},
                        },
                    },
                    "overall_notes": {"type": "string"},
                    "fabricated_content": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
        )

    def get_auto_scorer(self) -> AutoScorer | None:
        return PF2eAutoScorer()

    def get_auto_score_weight(self) -> float:
        return 0.3


def get_pack() -> ChallengePack:
    return PF2ePack()
