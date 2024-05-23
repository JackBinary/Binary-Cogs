import json
import os

async def update_channel_config(channel_id, guild_id, key, value, config_dir):
    channel_config_path = os.path.join(config_dir, guild_id, f"{channel_id}.json")
    if os.path.exists(channel_config_path):
        with open(channel_config_path, 'r') as config_file:
            channel_config = json.load(config_file)
        channel_config[key] = value
        with open(channel_config_path, 'w') as config_file:
            json.dump(channel_config, config_file, indent=4)
