const fs = require('fs');
const file = '/Users/sujayabhat/Downloads/Agentic OS/jatayu/web/static/app.js';
let content = fs.readFileSync(file, 'utf8');

// Prepend the alert if not already there
if (!content.includes('alert("JATAYU APP.JS V7 LOADED");')) {
    content = 'alert("JATAYU APP.JS V7 LOADED");\n' + content;
}

// Inject into handleDone
content = content.replace(
    'if (fullText && ttsEnabled) {',
    `if (typeof _debugLog === 'function') _debugLog("Inside handleDone. fullText=" + !!fullText + " ttsEnabled=" + ttsEnabled);\n    if (fullText && ttsEnabled) {`
);

fs.writeFileSync(file, content);
console.log("Patched alert and handleDone");
