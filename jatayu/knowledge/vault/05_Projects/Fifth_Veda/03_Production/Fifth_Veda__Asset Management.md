---
title: Asset Management
category: Production
project: Fifth Veda
owner: Sujay Bhat
status: Active
type: Standard
tags:
  - asset-management
  - file-conventions
  - google-omni
related:
  - "[[Fifth_Veda__Visual Operating System]]"
  - "[[Fifth_Veda__Version Control]]"
aliases:
  - Asset Management
  - Asset Management.md
---

# Asset Management

## Folder Organization
Assets are structured strictly by Season and Episode to maintain a machine-sortable database.
*   **Structure:** `/Season[X]/S[X]E[XX]_[Topic_Slug]/`[cite: 11].
*   **Subfolders:** Each episode directory contains explicit subfolders for `/research`, `/script`, `/assets` (containing Omni Ingredients), `/renders`, and `/final`[cite: 11].

## Generated Assets & Ingredient Naming
Visual reference stills (Ingredients) generated for Google Omni must be named clearly and consistently across the entire episode[cite: 12]. 
*   **Format:** `INGREDIENT_[SUBJECT]_[IDENTIFIER]`
*   *Examples:* `INGREDIENT_MANUSCRIPT_01`, `INGREDIENT_EXPERT_MEHTA`, `INGREDIENT_CHATURANGA_BOARD`[cite: 12].
*   The exact name string must be reused in every motion prompt that requires it[cite: 12].

## Asset Naming Conventions
Final video deliverables and master project files must adhere to the fixed sortable pattern.
*   **Format:** `5V_S[Season]E[Episode]_[TopicSlug]_FINAL.mp4`[cite: 11].

## Reuse Philosophy
The library compounds in value. Ingredients, visual B-roll, and expert character stills are preserved specifically for reuse in future episodes addressing the same primary texts, locations, or historical figures[cite: 7].
