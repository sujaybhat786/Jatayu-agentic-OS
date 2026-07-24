from jatayu.plugins.anythingllm.tools import AnythingLLMTools
import asyncio

tools = AnythingLLMTools("http://localhost:3001/api/v1")

questions = [
    "Who is Sujay Bhat?",
    "Who is Tejaswini Hegde?",
    "Who is Ekansh Rastogi?",
    "What is Artificial Budhi?",
    "What is Fifth Veda?",
    "What is our hiring philosophy?",
    "Who makes strategic decisions?",
    "What are our current priorities?"
]

for q in questions:
    res = tools.knowledge_search({"query": q})
    print(f"Q: {q}")
    print(f"A: {res.data['response'][:150]}...")
    print("-" * 20)
