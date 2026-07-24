import os

vault_dir = "/Users/sujayabhat/Downloads/Agentic OS/jatayu/knowledge/vault"
scratch_dir = "/Users/sujayabhat/.gemini/antigravity/brain/016c0096-93be-43ea-85a5-b1d1f7b0b594/scratch"

def write_note(folder, filename, category, domain, tags, related_people, related_projects, content):
    frontmatter = f"""---
title: {filename.replace('.md', '')}
category: {category}
domain: {domain}
owner: Sujay Bhat
privacy: Internal
created: 2026-07-15
updated: 2026-07-15
tags: [{', '.join(tags)}]
related_people: [{', '.join(['[[' + p + ']]' for p in related_people])}]
related_projects: [{', '.join(['[[' + p + ']]' for p in related_projects])}]
---

{content}
"""
    with open(os.path.join(vault_dir, folder, filename), "w") as f:
        f.write(frontmatter)

# Company Notes
write_note("01_Company", "Artificial Budhi Overview.md", "Company", "Knowledge", ["mission", "vision"], ["Sujay Bhat"], ["JATAYU", "Artificial Budhi"], 
"# Artificial Budhi Overview\n\n**Mission:** To create amazing products and content using AI that delight people and push the boundaries of creativity.\n**Vision:** To be a leading AI-powered media and technology studio.\n**Tagline:** We make cool stuff with AI.\n\nSee also: [[Company Story and Milestones]], [[Brand Positioning]]")

write_note("01_Company", "Strategic Objectives.md", "Company", "Strategy", ["strategy", "kpi"], ["Sujay Bhat"], ["JATAYU", "AI Gurukula"], 
"# Strategic Objectives (Next 12 Months)\n\n- Launch and Grow [[AI Gurukula]]\n- Deploy [[Fifth Veda]] Shorts\n- Release Key Products ([[JATAYU]], Shloka App)\n- Scale [[Artificial Budhi Studios]]")

write_note("02_Organization", "Organization Structure.md", "Organization", "Knowledge", ["orgchart"], ["Sujay Bhat", "Tejaswini Hegde", "Ekansh Rastogi"], ["Artificial Budhi"], 
"# Organization Structure\n\nArtificial Budhi is a founder-led AI-native venture studio.\n- [[Sujay Bhat]]: Founder & Captain\n- [[Tejaswini Hegde]]: Human Resources\n- [[Ekansh Rastogi]]: AI Content Creator Intern\n\nDivisions: [[Media And Studios Divisions]], [[Labs And IP Divisions]]")

write_note("08_SOPs", "Decision Making Model.md", "SOP", "Operations", ["decisions"], ["Sujay Bhat"], [], 
"# Decision Making Model\n\n**Macro Decisions**: Company Vision, Product Direction, Hiring, Strategy (Owner: [[Sujay Bhat]])\n**Micro Decisions**: Creative Execution, Editing Style (Owner: Person responsible for project).")

write_note("08_SOPs", "Project Classification and Privacy.md", "SOP", "Operations", ["classification"], [], [], 
"# Project Classification\n\n- Idea, Experiment, Active Project, Product, Client Work, Archive.\n\n# Information Privacy\n- Personal, Internal, Team Shared, Public.")

write_note("03_Founder", "Sujay Bhat Profile.md", "Founder", "Identity", ["founder"], ["Sujay Bhat"], ["JATAYU"], 
"# Sujay Bhat Profile\n\nThe Captain believes: I am God. He is the creator of its vision.\n**Strengths**: Vision, Creativity, Leadership, Calmness.\n**Weaknesses**: Procrastination, Context switching, Novelty addiction.\n\nSee [[Captain Operating System]]")

write_note("03_Founder", "Captain Operating System.md", "Founder", "Operations", ["mindset"], ["Sujay Bhat"], ["JATAYU"], 
"# Captain Operating System\n\nRelationship with [[JATAYU]]: JATAYU is the Captain's second brain, coach, and mirror. The First Law of JATAYU is: Protect the Captain from the Captain.\n\nCore Principles:\n1. Dream infinitely. Execute finitely.\n2. Finish before starting.\n3. Build cool stuff with AI.")

write_note("04_Portfolio", "Ecosystem Blueprint.md", "Portfolio", "Strategy", ["blueprint"], ["Sujay Bhat"], ["Artificial Budhi"], 
"# Ecosystem Blueprint\n\nPriority 1: [[Artificial Budhi]]\nPriority 2: [[Fifth Veda]]\nPriority 3: [[JATAYU]]\nPriority 4: [[AI Gurukula]]\nPriority 5: [[Pinaka]]")

write_note("04_Portfolio", "Media And Studios Divisions.md", "Portfolio", "Divisions", ["media"], ["Sujay Bhat", "Ekansh Rastogi", "Ram Raghavan"], ["Artificial Budhi", "AI Itihasa", "AI Gurukula", "Clan Gandabherunda"], 
"# Media Division\nBuild audiences through AI content. (Brands: [[Artificial Budhi]], [[AI Itihasa]], [[AI Gurukula]], [[Clan Gandabherunda]], [[Fifth Veda]])\n\n# Studios Division\nProvide AI-powered creative services. (Client: [[My Content Smart Hub]])")

write_note("04_Portfolio", "Labs And IP Divisions.md", "Portfolio", "Divisions", ["labs", "ip"], ["Sujay Bhat"], ["JATAYU", "Pinaka"], 
"# Labs Division\nResearch, build and experiment with AI products. (Projects: [[JATAYU]], Shloka App, AI Pre-Wedding Platform)\n\n# IP Division\nCreate original intellectual property. (Projects: [[Fifth Veda]], [[Pinaka]])")

print("Notes populated.")
