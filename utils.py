from telegram import MessageEntity
import re

def format_custom_emoji(text: str, CE: dict):
    """
    Replace placeholders like {rocket} with custom emoji entities.
    Returns (text_with_emojis, entities_list)
    """
    entities = []
    new_text = text
    offset = 0

    for match in re.finditer(r"{(.*?)}", text):
        name = match.group(1)
        info = CE.get(name, {})
        emoji_char = info.get("char", "")
        # ID emoji disimpan di entities[0]["custom_emoji_id"] (struktur Config),
        # bukan di key "id" — dukung dua-duanya
        emoji_id = info.get("id")
        if not emoji_id:
            ents = info.get("entities") or []
            if ents and isinstance(ents[0], dict):
                emoji_id = ents[0].get("custom_emoji_id")
        start = match.start() + offset
        end = match.end() + offset

        if emoji_id:
            new_text = new_text[:start] + emoji_char + new_text[end:]
            length = len(emoji_char)
            entities.append(MessageEntity(
                type="custom_emoji",
                offset=start,
                length=length,
                custom_emoji_id=emoji_id
            ))
            offset += len(emoji_char) - (end - start)
        else:
            # fallback: normal emoji
            new_text = new_text[:start] + emoji_char + new_text[end:]
            offset += len(emoji_char) - (end - start)

    return new_text, entities
