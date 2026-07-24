import os
import shutil

vault_dir = "/Users/sujayabhat/Downloads/Agentic OS/jatayu/knowledge/vault"

folders = [
    "00_Inbox",
    "00_Crown",
    "01_Company",
    "02_Organization",
    "03_Founder",
    "04_Portfolio",
    "05_Projects",
    "06_People",
    "07_Clients",
    "08_SOPs",
    "09_Meetings",
    "10_Research",
    "11_Archive"
]

project_folders = [
    "Artificial Budhi",
    "Fifth Veda",
    "AI Gurukula",
    "JATAYU",
    "Pinaka",
    "Artificial Budhi Studios",
    "AI Itihasa",
    "Clan Gandabherunda"
]

for f in folders:
    os.makedirs(os.path.join(vault_dir, f), exist_ok=True)
    with open(os.path.join(vault_dir, f, "README.md"), "w") as readme:
        readme.write(f"# {f}\n\nThis directory holds {f.split('_')[-1]} related knowledge.\n\n")

for pf in project_folders:
    os.makedirs(os.path.join(vault_dir, "05_Projects", pf), exist_ok=True)
    with open(os.path.join(vault_dir, "05_Projects", pf, "README.md"), "w") as readme:
        readme.write(f"# {pf} Project\n\nNotes and assets for {pf}.\n\n")

# Create Client
os.makedirs(os.path.join(vault_dir, "07_Clients", "Ram Raghavan"), exist_ok=True)
client_note = """---
title: My Content Smart Hub
category: Clients
domain: Business
owner: Sujay Bhat
privacy: Internal
created: 2026-07-15
updated: 2026-07-15
tags: [client, studio]
related_people: [[Ram Raghavan]], [[Sujay Bhat]]
related_projects: [[Artificial Budhi Studios]]
---

# My Content Smart Hub

**Client**: [[Ram Raghavan]]
**Engagement**: AI-generated social media videos and posts under our creative studio brand, co-branded with Ram's platform.
**Status**: Active
**Started**: July 2026
"""
with open(os.path.join(vault_dir, "07_Clients", "Ram Raghavan", "My Content Smart Hub.md"), "w") as f:
    f.write(client_note)

# Create People
people = {
    "Sujay Bhat": "Role: Founder, Captain & Chief Decision Maker\nResponsibilities: Company Strategy, Vision & Direction, Product Management, AI Engineering, Creative Direction\nRelated Projects: [[JATAYU]], [[Fifth Veda]], [[Pinaka]], [[AI Gurukula]], [[Artificial Budhi]]\nReporting Structure: Founder\nInternal Notes: Visionary leader building AI-native venture studio.",
    "Tejaswini Hegde": "Role: Human Resources\nResponsibilities: Recruitment, Candidate Communication, Hiring Coordination, Managing the AI Influencer Brand (Kamini Kasturi)\nRelated Projects: [[Kamini Kasturi]]\nReporting Structure: Reports to [[Sujay Bhat]]",
    "Ekansh Rastogi": "Role: AI Content Creator Intern\nResponsibilities: Operate the AI Gurukula content pipeline, AI Tutorial Research, Script Writing, Video Editing, Publishing Content\nRelated Projects: [[AI Gurukula]]\nReporting Structure: Reports to [[Sujay Bhat]]",
    "Ram Raghavan": "Role: Client / Partner\nResponsibilities: Owner of My Content Smart Hub in the UK\nRelated Projects: [[My Content Smart Hub]]\nReporting Structure: External Client"
}

for name, details in people.items():
    note = f"""---
title: {name}
category: People
domain: Organization
owner: Sujay Bhat
privacy: Internal
created: 2026-07-15
updated: 2026-07-15
tags: [person, team]
related_people: 
related_projects: 
---

# {name}

{details}
"""
    with open(os.path.join(vault_dir, "06_People", f"{name}.md"), "w") as f:
        f.write(note)

# Root README
root_readme = """# Obsidian Vault Architecture

This vault is the **Canonical Source of Truth** for Artificial Budhi and JATAYU.
AnythingLLM acts only as the Semantic Index. Knowledge belongs here first.

## Hierarchy
- **00_Inbox**: Temporary landing area for imported documents.
- **01_Company** to **11_Archive**: Structured knowledge following PARA/Zettelkasten principles.

## Metadata Standards
All notes must contain YAML frontmatter:
```yaml
title: Note Title
category: Category
domain: Domain
owner: Person
privacy: Internal/Public
created: YYYY-MM-DD
updated: YYYY-MM-DD
tags: [tags]
related_people: [[Name]]
related_projects: [[Project]]
```
"""
with open(os.path.join(vault_dir, "README.md"), "w") as f:
    f.write(root_readme)

print("Scaffold complete.")
