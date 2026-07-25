const fs = require('fs');
const file = '/Users/sujayabhat/Downloads/Agentic OS/jatayu/web/static/app.js';
let content = fs.readFileSync(file, 'utf8');

content = content.replace(
    'ws.onmessage = (event) => {',
    `ws.onmessage = (event) => {\n        if (typeof _debugLog === 'function') _debugLog("WS Event: " + (JSON.parse(event.data).type));`
);

content = content.replace(
    'function handleDone(fullText) {',
    `function handleDone(fullText) {\n    if (typeof _debugLog === 'function') _debugLog("handleDone called");`
);

fs.writeFileSync(file, content);
console.log("Patched WS and handleDone");
