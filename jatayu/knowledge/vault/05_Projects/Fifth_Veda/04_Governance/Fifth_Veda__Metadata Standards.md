---
title: Metadata Standards
category: Governance
project: Fifth Veda
owner: Sujay Bhat
status: Active
type: Standard
tags:
  - metadata
  - tagging
  - naming-conventions
related:
  - "[[Fifth_Veda__Knowledge Management]]"
  - "[[Fifth_Veda__Folder Architecture]]"
aliases:
  - Metadata Standards
  - Metadata Standards.md
---

# Metadata Standards

## Metadata Philosophy
Every Clip record must carry specific baseline metadata to allow the knowledge system to answer structural questions without manual audits[cite: 18]. At minimum, this metadata includes:
*   Pillar[cite: 18]
*   Framework[cite: 18]
*   Audience type[cite: 18]
*   Hook type[cite: 18]
*   Primary source list[cite: 18]
*   Season[cite: 18]

## Naming Conventions
Clip identifiers follow a fixed, sortable pattern so that identifiers remain stable and machine-sortable regardless of publishing order[cite: 18]. 
*   **Format:** `Season`, `pillar code`, and `sequence number` within that pillar for that Season, followed by a short topic slug[cite: 18].
*   **Example:** `S1E01_TimeDilation`[cite: 18].

## Knowledge Relationships & Backlinking
Clips are linked to one another along three specific relationship types, which must be recorded explicitly rather than left implicit[cite: 18]:
1.  **Same-pillar:** Adjacent content within one subject territory[cite: 18].
2.  **Same-source:** Multiple Clips drawing on the same primary text or archive[cite: 18].
3.  **Cross-pillar comparison:** A deliberate pairing (e.g., a Science-pillar and Philosophy-pillar Clip addressing the same historical period from different angles)[cite: 18].

Every Clip record must backlink to its pillar record, its framework record, and every primary source it cites[cite: 18]. Consequently, every source record accumulates backlinks from every Clip that has used it, allowing efficient downstream reviews if a source is updated or retracted[cite: 18].
