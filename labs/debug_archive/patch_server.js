const fs = require('fs');
const file = '/Users/sujayabhat/Downloads/Agentic OS/jatayu/web/server.py';
let content = fs.readFileSync(file, 'utf8');

const replacement = `
from fastapi.staticfiles import StaticFiles

class NoCacheStaticFiles(StaticFiles):
    def is_not_modified(self, response_headers, request_headers) -> bool:
        return False
        
    def file_response(self, full_path, stat_result, scope, status_code=200):
        resp = super().file_response(full_path, stat_result, scope, status_code)
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return resp

app.mount("/static", NoCacheStaticFiles(directory=str(STATIC_DIR)), name="static")
`;

content = content.replace('app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")', replacement);
fs.writeFileSync(file, content);
console.log("Patched server.py for static files caching");
