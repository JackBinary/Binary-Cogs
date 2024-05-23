import json
import os

async def create_character(character_name, character_persona, config_dir):
    characters_dir = os.path.join(config_dir, "characters")
    if not os.path.exists(characters_dir):
        os.makedirs(characters_dir)
    character_path = os.path.join(characters_dir, f"{character_name}.json")
    character_config = {
        "Name": character_name,
        "Persona": character_persona
    }
    with open(character_path, 'w') as config_file:
        json.dump(character_config, config_file, indent=4)

async def delete_character(character_name, config_dir):
    characters_dir = os.path.join(config_dir, "characters")
    character_path = os.path.join(characters_dir, f"{character_name}.json")
    if os.path.exists(character_path):
        os.remove(character_path)

async def show_persona(character_name, config_dir):
    characters_dir = os.path.join(config_dir, "characters")
    character_path = os.path.join(characters_dir, f"{character_name}.json")
    if os.path.exists(character_path):
        with open(character_path, 'r') as config_file:
            character_config = json.load(config_file)
        return character_config["Persona"]
    return None

async def update_persona(character_name, new_persona, config_dir):
    characters_dir = os.path.join(config_dir, "characters")
    character_path = os.path.join(characters_dir, f"{character_name}.json")
    if os.path.exists(character_path):
        with open(character_path, 'r') as config_file:
            character_config = json.load(config_file)
        character_config["Persona"] = new_persona
        with open(character_path, 'w') as config_file:
            json.dump(character_config, config_file, indent=4)
