import asyncio
from jatayu.web.server import speak_text
from fastapi import Request
import json

class MockRequest:
    async def json(self):
        return {"text": "I am testing the speech formatter"}

async def run():
    req = MockRequest()
    res = await speak_text(req)
    print(res.status_code)
    print(len(res.body))
    print(dict(res.headers))

asyncio.run(run())
