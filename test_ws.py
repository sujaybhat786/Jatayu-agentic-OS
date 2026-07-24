import asyncio
import websockets
import json

async def test():
    async with websockets.connect("ws://localhost:8000/ws") as ws:
        await ws.send(json.dumps({"type": "chat", "text": "Hello Jatayu"}))
        try:
            while True:
                msg = await asyncio.wait_for(ws.recv(), timeout=30.0)
                print(f"Received: {msg}")
        except asyncio.TimeoutError:
            print("Timeout waiting for response.")

asyncio.run(test())
