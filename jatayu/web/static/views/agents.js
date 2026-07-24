'use strict';
const DEFAULT_AGENTS = [
    { name:'Research', icon:'🔬', status:'idle', task:'' },
    { name:'Email', icon:'📧', status:'idle', task:'' },
    { name:'Calendar', icon:'📅', status:'idle', task:'' },
    { name:'Social', icon:'📡', status:'idle', task:'' },
    { name:'Browser', icon:'🌐', status:'idle', task:'' },
    { name:'Knowledge', icon:'🧠', status:'idle', task:'' },
    { name:'Task', icon:'📋', status:'idle', task:'' },
    { name:'Trend', icon:'📈', status:'idle', task:'' },
];
const NODE_POSITIONS = [
    {x:50,y:5},{x:85,y:20},{x:95,y:55},{x:80,y:85},
    {x:50,y:95},{x:15,y:85},{x:2,y:55},{x:15,y:20},
];

async function loadAgentsView() {
    const network = document.getElementById('agNetwork');
    if (!network) return;
    let agents = [...DEFAULT_AGENTS];
    try {
        const res = await fetch('/api/agents');
        const data = await res.json();
        if (data && Object.keys(data).length > 0) {
            Object.values(data).forEach(a => {
                const match = agents.find(da => da.name.toLowerCase() === (a.display_name||a.name||'').toLowerCase());
                if (match) { match.status = a.status === 'connected' ? 'running' : 'idle'; match.task = a.purpose || ''; }
            });
        }
    } catch (e) {}
    renderAgentNodes(network, agents);
}

function renderAgentNodes(container, agents) {
    container.querySelectorAll('.ag-node').forEach(n => n.remove());
    const svgLines = container.querySelector('.ag-svg-lines');
    if (svgLines) svgLines.innerHTML = '';
    const centerX = 50, centerY = 50;
    agents.forEach((agent, i) => {
        const pos = NODE_POSITIONS[i % NODE_POSITIONS.length];
        const node = document.createElement('div');
        node.className = 'ag-node';
        node.dataset.status = agent.status;
        node.style.left = `calc(${pos.x}% - 55px)`;
        node.style.top = `calc(${pos.y}% - 55px)`;
        node.title = agent.task || agent.name;
        node.innerHTML = `<div class="ag-node-icon">${agent.icon}</div><div class="ag-node-name">${agent.name}</div><div class="ag-node-status ${agent.status}"></div>`;
        container.appendChild(node);
        if (svgLines) {
            const line = document.createElementNS('http://www.w3.org/2000/svg','line');
            line.setAttribute('x1',`${centerX}%`); line.setAttribute('y1',`${centerY}%`);
            line.setAttribute('x2',`${pos.x}%`); line.setAttribute('y2',`${pos.y}%`);
            line.setAttribute('stroke', agent.status==='running' ? 'rgba(52,211,153,0.4)' : 'rgba(201,149,44,0.15)');
            line.setAttribute('stroke-width','1');
            svgLines.appendChild(line);
        }
    });
}
