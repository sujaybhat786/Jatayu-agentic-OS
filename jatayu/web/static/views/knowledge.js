'use strict';
const KNOWLEDGE_CATEGORIES = [
    {id:'company',name:'Company',icon:'🏢',notes:8,x:15,y:20},
    {id:'organization',name:'Organization',icon:'🏛️',notes:5,x:60,y:15},
    {id:'founder',name:'Founder',icon:'👤',notes:4,x:15,y:65},
    {id:'portfolio',name:'Portfolio',icon:'📁',notes:5,x:60,y:60},
];
const KB_CONNECTIONS = [['company','organization'],['company','founder'],['organization','portfolio'],['founder','portfolio']];

function loadKnowledge() { renderKnowledgeBoard(); }

function renderKnowledgeBoard() {
    const board = document.getElementById('kbBoard');
    if (!board) return;
    board.querySelectorAll('.kb-node').forEach(n=>n.remove());
    const svg = board.querySelector('.kb-board-svg');
    if (svg) svg.innerHTML = '';
    KNOWLEDGE_CATEGORIES.forEach(cat => {
        const node = document.createElement('div');
        node.className = 'kb-node'; node.dataset.id = cat.id;
        node.style.left = `${cat.x}%`; node.style.top = `${cat.y}%`;
        node.innerHTML = `<div class="kb-node-icon">${cat.icon}</div><div class="kb-node-name">${cat.name}</div><div class="kb-node-count">${cat.notes} notes</div>`;
        board.appendChild(node);
    });
    if (svg) {
        KB_CONNECTIONS.forEach(([fromId,toId]) => {
            const from = KNOWLEDGE_CATEGORIES.find(c=>c.id===fromId);
            const to = KNOWLEDGE_CATEGORIES.find(c=>c.id===toId);
            if (!from||!to) return;
            const line = document.createElementNS('http://www.w3.org/2000/svg','line');
            line.setAttribute('x1',`${from.x+5}%`); line.setAttribute('y1',`${from.y+5}%`);
            line.setAttribute('x2',`${to.x+5}%`); line.setAttribute('y2',`${to.y+5}%`);
            line.setAttribute('stroke','rgba(201,149,44,0.2)'); line.setAttribute('stroke-width','1');
            line.setAttribute('stroke-dasharray','4 4');
            svg.appendChild(line);
        });
    }
}
