const fs = require('fs');
const file = '/Users/sujayabhat/Downloads/Agentic OS/jatayu/web/static/app.js';
let content = fs.readFileSync(file, 'utf8');

// Replace updateBeacon to be safe
content = content.replace(
    'function updateBeacon(status) {',
    'function updateBeacon(status) {\n    if (!statusBeacon) return;'
);

// Replace handlePanels (if existing) or any direct assignment
content = content.replace(
    'function updatePanels(data) {',
    'function updatePanels(data) {\n    if (!data) return;'
);

// We need to safely guard any innerHTML or textContent of missing panels
const replacements = [
    [/draftsPanel\.innerHTML/g, 'if (draftsPanel) draftsPanel.innerHTML'],
    [/memoryPanel\.innerHTML/g, 'if (memoryPanel) memoryPanel.innerHTML'],
    [/footerModel\.textContent/g, 'if (footerModel) footerModel.textContent'],
    [/footerTools\.textContent/g, 'if (footerTools) footerTools.textContent']
];

for (const [regex, replacement] of replacements) {
    content = content.replace(regex, replacement);
}

fs.writeFileSync(file, content);
console.log("Patched app.js with safe checks");
