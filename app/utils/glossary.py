import json
import os


class GlossaryManager:
    def __init__(self, llm_dir: str):
        self.glossaries_dir = os.path.join(llm_dir, "glossaries")
        
        os.makedirs(os.path.join(self.glossaries_dir, "core"), exist_ok=True)
        os.makedirs(os.path.join(self.glossaries_dir, "games"), exist_ok=True)
        os.makedirs(os.path.join(self.glossaries_dir, "mods"), exist_ok=True)

    def get_available_files(self) -> dict:
        """Возвращает список игр и сгруппированный список модов."""
        def _get_files(folder):
            path = os.path.join(self.glossaries_dir, folder)
            if not os.path.exists(path):
                return []
            return [f for f in os.listdir(path) if f.endswith('.json')]

        games = _get_files("games")
        all_mods = _get_files("mods")
        
        # Группируем моды по играм.
        # Если файл называется 'minecraft_create.json', 
        # то 'minecraft' станет ключом, а 'minecraft_create.json' попадет в список.
        mods_by_game = {game.replace('.json', ''): [] for game in games}
        
        for mod in all_mods:
            # Берем префикс до первого подчеркивания
            prefix = mod.split('_')[0] 
            if prefix in mods_by_game:
                mods_by_game[prefix].append(mod)
                
        return {
            "games": games,
            "mods_by_game": mods_by_game
        }

    def load_layers(self, game_name: str, mod_name: str = None) -> dict:
        glossary = {}
        # 1. Core
        core_path = os.path.join(self.glossaries_dir, "core", "base.json")
        if os.path.exists(core_path):
            with open(core_path, "r", encoding="utf-8-sig") as f:
                glossary.update(json.load(f))
        # 2. Game
        if game_name:
            game_path = os.path.join(self.glossaries_dir, "games", game_name)
            if os.path.exists(game_path):
                with open(game_path, "r", encoding="utf-8-sig") as f:
                    glossary.update(json.load(f))
        # 3. Mod
        if mod_name:
            mod_path = os.path.join(self.glossaries_dir, "mods", mod_name)
            if os.path.exists(mod_path):
                with open(mod_path, "r", encoding="utf-8-sig") as f:
                    glossary.update(json.load(f))
        return glossary