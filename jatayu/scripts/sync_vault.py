import os
import glob
import yaml
import asyncio
from jatayu.brain import Brain

def parse_frontmatter(content):
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            try:
                metadata = yaml.safe_load(parts[1])
                return metadata, parts[2]
            except:
                pass
    return {}, content

async def sync():
    print("Initializing JATAYU Brain...")
    brain = Brain()
    
    vault_dir = "/Users/sujayabhat/Downloads/Agentic OS/jatayu/knowledge/vault"
    md_files = glob.glob(os.path.join(vault_dir, "**/*.md"), recursive=True)
    
    print(f"Found {len(md_files)} notes in the vault. Syncing to AnythingLLM...")
    
    for f in md_files:
        with open(f, "r") as file:
            content = file.read()
            
        metadata, body = parse_frontmatter(content)
        title = metadata.get("title", os.path.basename(f).replace(".md", ""))
        privacy = metadata.get("privacy", "Internal").lower().replace(" ", "_")
        
        # We use the my-workspace collection since it's the only one that exists
        collection = "my-workspace"
        
        print(f"Syncing: {title} (Privacy: {collection})")
        
        # Add metadata headers into the text body so the LLM understands it semantically
        metadata_str = "\n".join([f"{k.capitalize()}: {v}" for k, v in metadata.items() if k != "title"])
        full_text = f"Title: {title}\n{metadata_str}\n\n{body}"
        
        res = brain.knowledge_manager.upload(content=full_text, title=title, collection=collection)
        if res.get("status") == "error":
            print(f"  Error: {res.get('summary')}")
        else:
            print(f"  Success: Indexed into {collection}")
            
    print("Sync complete.")

if __name__ == "__main__":
    asyncio.run(sync())
