import os
import json
import textwrap
import re
import sseclient  # pip install sseclient-py
import requests

async def handle_message(cog, message):
    if message.author.bot:
        return

    prefixes = await cog.bot.get_valid_prefixes(message.guild)
    if any(message.content.startswith(prefix) for prefix in prefixes):
        return

    if message.channel.id in cog.listening_channels:
        guild_id = str(message.guild.id)
        channel_id = str(message.channel.id)
        channel_config_path = os.path.join(cog.config_dir, guild_id, f"{channel_id}.json")
        if not os.path.exists(channel_config_path):
            await message.channel.send("Configuration for this channel is missing.")
            return
        
        with open(channel_config_path, 'r') as config_file:
            channel_config = json.load(config_file)
        
        channel_config['chat_history'].append(f"{message.author.nick if message.author.nick else message.author.name}: {message.content}")
        with open(os.path.join(cog.config_dir, "characters", f"{channel_config['character']}.json"), 'r') as config_file:
            character = json.load(config_file)

        rendered_history = "\n".join(channel_config['chat_history'])

        prompt = textwrap.dedent(f"""
            You are in a chat room with multiple participants.
            Below is a transcript of recent messages in the conversation.
            Write the next one to three messages that you would send in this
            conversation, from the point of view of the participant named
            {character['Name']}.

            {character['Persona']}

            All responses you write must be from the point of view of
            {character['Name']}.

            ### Transcript:
            {rendered_history}
            {character['Name']}:
        """)

        data = {
            "mode": "instruct",
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
            "max_tokens": channel_config["max_tokens"] if channel_config["max_tokens"] is not None else 200
        }
        
        # Send the request to the LLM server
        stream_response = requests.post(
            cog.llm_server_url,
            headers={"Content-Type": "application/json"},
            json=data,
            verify=False,
            stream=True
        )
        client = sseclient.SSEClient(stream_response)
        assistant_message = ''
        message_store = []
        # Regex pattern to match sentence-ending punctuation or newline
        pattern = r'([.!?])|\n'

        for event in client.events():
            payload = json.loads(event.data)
            print(payload)
            chunk = payload['choices'][0]['text']
            assistant_message += chunk

            # Split the message using the regex pattern
            parts = re.split(pattern, assistant_message)

            # Process each part
            i = 0
            while i < len(parts) - 1:
                part = parts[i]
                if part and part.strip():
                    part = part.strip()
                    # Check if the next part is a punctuation mark
                    if i + 1 < len(parts) and parts[i + 1] in ['.', '!', '?']:
                        part += parts[i + 1]  # Append the punctuation mark
                        i += 1  # Skip the punctuation mark in the next iteration
                    await message.channel.send(part)
                    message_store.append(part)
                i += 1

            # Keep the last part (which may be an incomplete message) in assistant_message
            assistant_message = parts[-1]

        # Send any remaining text that didn't end with a punctuation or newline
        if assistant_message.strip():
            await message.channel.send(assistant_message.strip())
            message_store.append(assistant_message.strip())

        assistant_message = "\n".join(message_store)
        
        channel_config['chat_history'].append(f"{channel_config['character']}: {assistant_message}")
        with open(channel_config_path, 'w') as config_file:
            json.dump(channel_config, config_file, indent=4)
