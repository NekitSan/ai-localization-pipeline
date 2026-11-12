import json
import os


class PromptRegistry:
    def __init__(self):
        self.skills = {
            "autonomous_game_transliteration": (
                "\n=== SKILL: GAME LORE & TRANSLITERATION ===\n"
                "You are an expert game translator. Translate the meaning of common words, but "
                "phonetically TRANSLITERATE proper nouns, fantasy terms, names, and titles into Russian (cyrillic).\n"
                "ALGORITHM:\n"
                "1. Check if 'entities_to_transliterate' is provided. If yes, those words MUST be written by sound (e.g., 'Ursa' -> 'Урса').\n"
                "2. For words NOT in the list: analyze their context. If a word is capitalized and represents a unique entity, "
                "weapon, or pet (e.g., 'Mjolnir hammer'), translate the item type but transliterate the name: 'Молот Мьёльнир'.\n"
                "3. Common adjectives (like 'Heavy', 'Ancient', 'Mighty') must be translated semantically, even if capitalized.\n"
                "4. Never leave raw English characters in the translated values."
            )
        }

    def get_skills(self, skill_keys: list[str]) -> str:
        result = ""
        for key in skill_keys:
            if key in self.skills:
                result += self.skills[key]
        return result

class PromptBuilder:
    def __init__(self, prompts_dir: str, glossary_mgr):
        self.prompts_dir = prompts_dir
        self.glossary_mgr = glossary_mgr
        self.registry = PromptRegistry()

    def build(self, game_name: str = None) -> str:
        with open(os.path.join(self.prompts_dir, "system_prompt.txt"), "r", encoding="utf-8") as f:
            final_prompt = f.read()

        # Всегда добавляем скилл транслитерации
        final_prompt += self.registry.get_skills(["autonomous_game_transliteration"])

        if game_name:
            game_rules_path = os.path.join(self.prompts_dir, "games", f"{game_name.replace('.json', '')}_rules.txt")
            if os.path.exists(game_rules_path):
                with open(game_rules_path, "r", encoding="utf-8") as f:
                    final_prompt += f"\n\n{f.read()}"

        glossary = self.glossary_mgr.load_layers(game_name)
        if glossary:
            final_prompt += f"\n\nCRITICAL GLOSSARY:\n{json.dumps(glossary, ensure_ascii=False)}"

        return final_prompt