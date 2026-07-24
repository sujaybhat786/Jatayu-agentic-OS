'use strict';
function loadDashboard() { _loadBriefing(); _loadDashStats(); _initQuickActions(); _loadTimeline(); }

async function _loadBriefing() {
    const greeting = document.getElementById('dashGreeting');
    const briefText = document.getElementById('dashBriefText');
    if (!greeting) return;
    const hour = new Date().getHours();
    const timeOfDay = hour < 12 ? 'morning' : hour < 17 ? 'afternoon' : 'evening';
    greeting.textContent = `Good ${timeOfDay}, Sujaya.`;
    try {
        const [reminders, schedule] = await Promise.all([
            fetch('/api/reminders').then(r => r.json()).catch(() => ({ reminders: [] })),
            fetch('/api/schedule').then(r => r.json()).catch(() => ({ tasks: [] })),
        ]);
        const taskCount = (schedule.tasks || []).length;
        const reminderCount = (reminders.reminders || []).length;
        let brief = '';
        if (taskCount > 0) brief += `You have ${taskCount} task${taskCount > 1 ? 's' : ''} scheduled today`;
        if (reminderCount > 0) brief += `${brief ? ', ' : 'You have '}${reminderCount} active reminder${reminderCount > 1 ? 's' : ''}`;
        if (!brief) brief = 'Your schedule is clear today';
        brief += '. JATAYU is online and ready.';
        if (briefText) briefText.textContent = brief;
    } catch (e) { if (briefText) briefText.textContent = 'JATAYU is online and ready.'; }
}

async function _loadDashStats() {
    const dateEl = document.getElementById('dashStatDate');
    const tasksEl = document.getElementById('dashStatTasks');
    const memoryEl = document.getElementById('dashStatMemory');
    const statusEl = document.getElementById('dashStatStatus');
    if (dateEl) dateEl.textContent = new Date().toLocaleDateString('en-IN', { weekday:'short', day:'numeric', month:'short' });
    try {
        const [schedule, memory] = await Promise.all([
            fetch('/api/schedule').then(r => r.json()).catch(() => ({ tasks: [] })),
            fetch('/api/memory').then(r => r.json()).catch(() => ({ memories: [] })),
        ]);
        if (tasksEl) tasksEl.textContent = (schedule.tasks || []).length;
        if (memoryEl) memoryEl.textContent = Array.isArray(memory) ? memory.length : (memory.memories || []).length;
        if (statusEl) { statusEl.textContent = 'Online'; statusEl.style.color = 'var(--status-ok)'; }
    } catch (e) { if (statusEl) statusEl.textContent = 'Unknown'; }
}

function _initQuickActions() {
    document.querySelectorAll('.dash-action-btn[data-route]').forEach(btn => {
        btn.addEventListener('click', () => { window.location.hash = btn.dataset.route; });
    });
}

function _loadTimeline() {
    const container = document.getElementById('dashTimeline');
    if (!container) return;
    const events = [
        { text: 'System started', time: 'Just now' },
        { text: 'Voice pipeline ready', time: 'On startup' },
        { text: 'Knowledge vault synced', time: 'On startup' },
        { text: 'Speech formatter active', time: 'On startup' },
    ];
    container.innerHTML = events.map(e => `
        <div class="dash-timeline-item">
            <div class="dash-timeline-text">${e.text}</div>
            <div class="dash-timeline-time">${e.time}</div>
        </div>`).join('');
}
