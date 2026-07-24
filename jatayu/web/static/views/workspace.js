'use strict';
async function loadWorkspace() {
    const container = document.getElementById('wsContainer');
    if (!container) return;
    let tasks = [];
    try {
        const [schedule, reminders] = await Promise.all([
            fetch('/api/schedule').then(r=>r.json()).catch(()=>({tasks:[]})),
            fetch('/api/reminders').then(r=>r.json()).catch(()=>({reminders:[]})),
        ]);
        (schedule.tasks||[]).forEach(t => tasks.push({
            text: typeof t==='string' ? t : (t.title||t.name||JSON.stringify(t)),
            status: t.done ? 'completed' : 'in-progress', due: t.due||'Today', assignee:'Me',
        }));
        (reminders.reminders||[]).forEach(r => tasks.push({
            text: typeof r==='string' ? r : (r.text||r.title||JSON.stringify(r)),
            status: r.done ? 'completed' : 'urgent', due: r.time||'Today', assignee:'Me',
        }));
    } catch(e){}
    if (tasks.length===0) tasks = [{text:'No tasks yet — ask JATAYU to create one',status:'in-progress',due:'Today',assignee:'JATAYU'}];
    renderTasks(container, tasks);
}
function renderTasks(container, tasks) {
    const groups = {urgent:[],  'in-progress':[], completed:[]};
    tasks.forEach(t => (groups[t.status]||groups['in-progress']).push(t));
    const labels = {urgent:'Urgent','in-progress':'In Progress',completed:'Completed'};
    let html = '';
    for (const [status, items] of Object.entries(groups)) {
        if (items.length===0) continue;
        const collapsed = status==='completed' ? 'collapsed' : '';
        html += `<div class="ws-group"><div class="ws-group-header ${status}" onclick="this.nextElementSibling.classList.toggle('collapsed')">${labels[status]} (${items.length})</div><div class="ws-group-content ${collapsed}">`;
        items.forEach(t => { html += `<div class="ws-task"><div class="ws-task-checkbox"></div><div class="ws-task-text">${t.text}</div><div class="ws-task-due">${t.due}</div><div class="ws-task-assignee">${t.assignee}</div></div>`; });
        html += `</div></div>`;
    }
    container.innerHTML = html || '<div class="ws-empty">No tasks found</div>';
}
