from jatayu.brain import Brain
brain = Brain()
res = brain.registry.execute("knowledge_search", {"query": "Tejaswini"})
print(type(res))
print(res)
