from jatayu.brain import Brain
brain = Brain()
res = brain.registry.execute("knowledge_search", {"query": "Who is Tejaswini?"})
print("RES IS:")
print(repr(res))
