const fs = require('fs');
const file = '/Users/sujayabhat/Downloads/Agentic OS/jatayu/web/server.py';
let content = fs.readFileSync(file, 'utf8');

const replacement = `
@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the main page."""
    with open(STATIC_DIR / "index.html", "rb") as f:
        html = f.read()
    return Response(
        content=html, 
        media_type="text/html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}
    )
`;

content = content.replace(/@app\.get\("\/", response_class=HTMLResponse\)[\s\S]*?return FileResponse\(STATIC_DIR \/ "index\.html"\)/m, replacement.trim());
fs.writeFileSync(file, content);
console.log("Patched index.html route");
