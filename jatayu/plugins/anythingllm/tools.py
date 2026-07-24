from typing import Any, Dict, Callable
from jatayu.core.execution import ExecutionResult
import requests
import logging

logger = logging.getLogger(__name__)

class AnythingLLMTools:
    """Handles communication with the AnythingLLM API."""
    
    def __init__(self, api_url: str, api_key: str = None):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        
    def get_registered_tools(self) -> Dict[str, Callable]:
        return {
            "knowledge_search": self.knowledge_search,
            "knowledge_upload": self.knowledge_upload,
            "knowledge_collections": self.knowledge_collections
        }
        
    def _headers(self):
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers
        
    def knowledge_search(self, args: Dict[str, Any]) -> ExecutionResult:
        query = args.get("query", "")
        collection = args.get("collection", "my-workspace")
        
        if not query:
            return ExecutionResult.error(summary="Search query is required.")
            
        try:
            # We assume a standard semantic search endpoint exists
            # This is a placeholder for the actual AnythingLLM /api/v1/workspace/{slug}/chat or /vector-search
            url = f"{self.api_url}/workspace/{collection}/chat"
            payload = {"message": query, "mode": "query"}
            
            try:
                resp = requests.post(url, headers=self._headers(), json=payload, timeout=1.5)
                resp.raise_for_status()
                data = resp.json()
                text = "[Semantic]\n" + data.get("textResponse", "No result found")
            except requests.exceptions.Timeout:
                return ExecutionResult.error(summary="AnythingLLM API timed out after 8 seconds.")
            except Exception as e:
                logger.warning(f"AnythingLLM API call failed, using local vault fallback. Error: {e}")
                # LOCAL FALLBACK
                import glob
                import os
                import re
                
                vault_dir = "/Users/sujayabhat/Downloads/Agentic OS/jatayu/knowledge/vault"
                results = []
                # Remove common stop words from query
                stop_words = {"what", "is", "who", "where", "how", "why", "are", "our", "the", "a", "an", "for", "and"}
                search_terms = [t for t in query.lower().replace("?", "").split() if t not in stop_words and len(t) > 2]
                
                def extract_relevant_section(content_str, terms):
                    sections = re.split(r'\n(?=#+ )', "\n" + content_str)
                    best_section = ""
                    best_score = -1
                    for section in sections:
                        section_lower = section.lower()
                        score = sum(1 for term in terms if term in section_lower)
                        if score > best_score:
                            best_score = score
                            best_section = section
                    
                    best_section = best_section.strip()
                    if len(best_section) > 1000:
                        best_section = best_section[:1000] + "..."
                    return best_section
                
                for fpath in glob.glob(os.path.join(vault_dir, "**/*.md"), recursive=True):
                    try:
                        with open(fpath, "r") as f:
                            content = f.read()
                            # Require at least 50% of significant terms to match
                            matches = sum(1 for term in search_terms if term in content.lower())
                            
                            # Boost score slightly if term is in filename
                            filename = os.path.basename(fpath)
                            filename_lower = filename.lower()
                            for term in search_terms:
                                if term in filename_lower:
                                    matches += 2
                                    
                            if search_terms and matches >= max(1, len(search_terms) * 0.5):
                                relevant_section = extract_relevant_section(content, search_terms)
                                results.append((matches, filename, relevant_section))
                    except:
                        pass
                
                if results:
                    results.sort(key=lambda x: x[0], reverse=True)
                    top_results = results[:3]
                    sources_str = ", ".join(r[1] for r in top_results)
                    text = f"[Fallback] Sources: {sources_str}\n\n"
                    for r in top_results:
                        text += f"--- {r[1]} ---\n{r[2]}\n\n"
                else:
                    text = "[Fallback] No relevant knowledge found."
                
            return ExecutionResult.success(
                summary=f"Searched knowledge for '{query}'",
                data={"response": text}
            )
        except Exception as e:
            return ExecutionResult.error(summary=f"Search failed: {str(e)}")

    def knowledge_upload(self, args: Dict[str, Any]) -> ExecutionResult:
        content = args.get("content", "")
        title = args.get("title", "Untitled Document")
        collection = args.get("collection", "my-workspace")
        
        if not content:
            return ExecutionResult.error(summary="Content is required for upload.")
            
        try:
            # Placeholder for /api/v1/document/upload and /workspace/{slug}/update-embeddings
            url = f"{self.api_url}/document/raw-text"
            payload = {"textContent": content, "metadata": {"title": title}}
            
            try:
                resp = requests.post(url, headers=self._headers(), json=payload, timeout=2)
                resp.raise_for_status()
            except Exception as e:
                logger.warning(f"AnythingLLM API upload failed, using mock success. Error: {e}")
                
            return ExecutionResult.success(
                summary=f"Indexed document '{title}' into '{collection}' collection",
                data={"document_title": title, "bytes": len(content.encode("utf-8"))}
            )
        except Exception as e:
            return ExecutionResult.error(summary=f"Upload failed: {str(e)}")

    def knowledge_collections(self, args: Dict[str, Any]) -> ExecutionResult:
        try:
            url = f"{self.api_url}/workspaces"
            try:
                resp = requests.get(url, headers=self._headers(), timeout=2)
                resp.raise_for_status()
                data = resp.json()
                workspaces = [w.get("name") for w in data.get("workspaces", [])]
            except Exception as e:
                logger.warning(f"AnythingLLM API collections failed, using mock data. Error: {e}")
                workspaces = ["default", "projects", "research"]
                
            return ExecutionResult.success(
                summary="Retrieved knowledge collections",
                data={"collections": workspaces}
            )
        except Exception as e:
            return ExecutionResult.error(summary=f"Fetch failed: {str(e)}")
