# Obsidian Vault Architecture

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
