import sys
import os
import asyncio
# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
print(project_root)
sys.path.insert(0, project_root)

from agents.prompt_manager.generator import GenerateManager, GenerationType, GenerationOptions
from agents.prompt_manager.character.models import CharacterModel as CharacterCard
from agents.prompt_manager.character.manager import DBManager as CharacterManager
from agents.prompt_manager.world_info.scanner import WorldInfoScanner

if __name__ == "__main__":
    character = CharacterManager().get_character_by_name("Seraphina")
    print(character)
    generator = GenerateManager(
        chat_id="test_user_123444",
        user_id="test_user_123444",
        character=character,
        world_info_scanner=WorldInfoScanner()
    )
    prompt = asyncio.run(generator.generate(GenerationType.NORMAL, GenerationOptions()))
    print(prompt)