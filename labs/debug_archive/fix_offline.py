import re

def get_offline_routing(user_text):
    text_lower = user_text.lower()
    if "hermes" in text_lower:
        return "hermes", "hermes_ask", "prompt"
    elif "open claw" in text_lower or "openclaw" in text_lower:
        return "openclaw", "openclaw_ask", "action"
    return None

print(get_offline_routing("Create a folder in my system downloads folder named Sujay Testing Using Hermes or Open Claw!"))
