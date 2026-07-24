import os
base_dir = "/Users/sujayabhat/Downloads/Agentic OS/jatayu/knowledge/vault/06_People"
people = ["Sujay Bhat", "Tejaswini Hegde", "Ekansh Rastogi", "Ram Raghavan"]

def get_frontmatter(name):
    return f"""---
title: {name}
category: People
domain: Knowledge
owner: Sujay Bhat
status: Active
privacy: Internal
created: 2026-07-15
last_updated: 2026-07-15
tags: [people, organization]
---

# {name}

This document contains the profile and role details for {name} within [[Artificial Budhi]].

{name} is a key member of the organization, contributing to projects such as [[JATAYU]], [[Fifth Veda]], and [[AI Gurukula]].
"""

for p in people:
    with open(os.path.join(base_dir, f"{p}.md"), "w") as f:
        f.write(get_frontmatter(p))
print("People notes created.")
