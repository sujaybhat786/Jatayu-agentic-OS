import asyncio
from jatayu.brain import Brain
brain = Brain()

async def test_fallback():
    user_text = "Create a folder in my system downloads folder named Sujay Testing Using Hermes or Open Claw!"
    plugin = brain.plugin_manager.plugins.get("hermes")
    def execute_fallback():
        return plugin.execute("delegate_coding", {"prompt": user_text})
    loop = asyncio.get_running_loop()
    res = await loop.run_in_executor(None, execute_fallback)
    print(res.status)
    print(res.data)

asyncio.run(test_fallback())
