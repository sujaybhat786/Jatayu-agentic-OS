import asyncio
import os
from dotenv import load_dotenv
from jatayu.comms.telegram.adapter import TelegramAdapter

async def test():
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("No telegram token in env")
        return
        
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"https://api.telegram.org/bot{token}/getUpdates")
        updates = resp.json().get("result", [])
        if not updates:
            print("No updates in telegram to extract chat_id")
            return
        chat_id = updates[-1]["message"]["chat"]["id"]
        
    print(f"Testing with chat_id={chat_id}")
    adapter = TelegramAdapter(token)
    
    # Try sending markdown text with parse_mode=HTML
    text = "Hello **world**, this is a test.\n- item 1\n- item 2"
    res = await adapter.send_text(str(chat_id), text)
    print("Result HTML:", res)

if __name__ == "__main__":
    asyncio.run(test())
