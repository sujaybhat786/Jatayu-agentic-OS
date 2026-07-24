'use strict';

// Global reference for today's state
let _chiefState = null;
let _chiefTasks = [];

async function loadChief() {
    const today = getLocalDateStr();
    await refreshChiefState(today);
    await loadSystemHealth();
}

function getLocalDateStr() {
    const now = new Date();
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, '0');
    const day = String(now.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

async function refreshChiefState(dateStr) {
    showLoader(true, "Synchronizing Chief state...");
    try {
        // Fetch tasks from /api/schedule to calculate deterministic progress
        const schedRes = await fetch('/api/schedule');
        const schedData = await schedRes.json();
        _chiefTasks = schedData.tasks || [];

        const res = await fetch(`/api/chief/state?date=${dateStr}`);
        _chiefState = await res.json();

        renderMorningBrief();
        renderHabits();
        renderAfternoonCheckin();
        renderNightDebrief();
        updateExecutionScore();
        renderExecutiveInsights();
    } catch (e) {
        console.error("Failed to load chief state", e);
    } finally {
        showLoader(false);
    }
}

async function loadSystemHealth() {
    try {
        const res = await fetch('/api/chief/system-health');
        const health = await res.json();
        const container = document.getElementById('chiefStatusGrid');
        if (!container) return;

        container.innerHTML = Object.entries(health).map(([name, status]) => {
            const isOk = status.includes('🟢') || status.includes('Synced') || status.includes('Active');
            const colorClass = isOk ? 'text-ok' : 'text-danger';
            return `
                <div class="chief-status-row">
                    <span class="label">${name}</span>
                    <span class="val ${colorClass}">${status}</span>
                </div>
            `;
        }).join('');
    } catch (e) {
        console.error("Failed to load system health", e);
    }
}

function showLoader(show, text = "Thinking...") {
    const loader = document.getElementById('chiefLoader');
    const loaderText = document.getElementById('chiefLoaderText');
    if (!loader) return;
    if (show) {
        if (loaderText) loaderText.textContent = text;
        loader.classList.add('active');
    } else {
        loader.classList.remove('active');
    }
}

// ── RENDERERS ──

function renderMorningBrief() {
    const brief = _chiefState.morning_brief;
    const morningBody = document.getElementById('chiefMorningBody');
    if (!morningBody) return;

    if (!brief) {
        morningBody.innerHTML = `
            <div class="chief-action-banner">
                <div style="font-size: 0.85rem; color: var(--text-secondary);">Your morning executive assessment has not been prepared.</div>
                <button class="chief-action-btn" onclick="generateMorningBrief()">Initialize Briefing</button>
            </div>
        `;
        return;
    }

    morningBody.innerHTML = `
        <div class="chief-briefing-header">
            <div class="chief-greeting">JATAYU Morning Assessment</div>
        </div>
        <div class="chief-mission-container">
            <div class="chief-mission-label">Today's Strategic Mission</div>
            <div class="chief-mission-text">${brief.mission}</div>
        </div>
        <div class="chief-brief-split">
            <div>
                <div style="font-size:0.75rem; text-transform:uppercase; color:var(--gold); font-weight:600; margin-bottom:10px; letter-spacing:0.05em;">Target Priorities</div>
                <div class="chief-list">
                    ${(brief.priorities || []).map((p, idx) => `
                        <div class="chief-list-item">
                            <span class="chief-list-num">${idx + 1}.</span>
                            <span>${p}</span>
                        </div>
                    `).join('')}
                </div>
            </div>
            <div>
                <div style="font-size:0.75rem; text-transform:uppercase; color:var(--gold); font-weight:600; margin-bottom:10px; letter-spacing:0.05em;">Execution Risks & Bottlenecks</div>
                <div class="chief-list">
                    ${(brief.risks || []).map(r => `
                        <div class="chief-list-item">
                            <span style="color:var(--status-warning)">⚠</span>
                            <span>${r}</span>
                        </div>
                    `).join('')}
                </div>
            </div>
        </div>
        <div style="margin-top:20px; padding-top:16px; border-top: 1px dashed var(--border-subtle);">
            <div class="chief-brief-split">
                <div class="chief-meta-items">
                    <div class="chief-meta-row"><span class="label">Hindu Calendar</span><span>${brief.hindu_calendar || 'N/A'}</span></div>
                    <div class="chief-meta-row"><span class="label">Weather</span><span>${brief.weather || 'N/A'}</span></div>
                </div>
                <div class="chief-meta-items">
                    <div class="chief-meta-row"><span class="label">AI Intelligence</span><span>${brief.ai_news || 'N/A'}</span></div>
                    <div class="chief-meta-row"><span class="label">Important Follow-ups</span><span>${(brief.follow_ups || []).join(', ') || 'None'}</span></div>
                </div>
            </div>
        </div>
    `;
}

function renderHabits() {
    const habits = _chiefState.habits || {};
    const container = document.getElementById('chiefHabitsList');
    if (!container) return;

    container.innerHTML = Object.entries(habits).map(([name, checked]) => `
        <div class="chief-habit-item ${checked ? 'checked' : ''}" onclick="toggleHabit('${name}')">
            <div class="chief-habit-label">
                <div class="chief-habit-checkbox"></div>
                <span>${name}</span>
            </div>
        </div>
    `).join('');
}

function renderAfternoonCheckin() {
    const checkin = _chiefState.afternoon_checkin;
    const body = document.getElementById('chiefCheckinBody');
    if (!body) return;

    if (!_chiefState.morning_brief) {
        body.innerHTML = `<div class="empty-state-sm">Waiting for Morning Briefing initialization.</div>`;
        return;
    }

    if (!checkin) {
        body.innerHTML = `
            <div class="chief-action-banner">
                <div style="font-size: 0.85rem; color: var(--text-secondary);">Verify current execution status against the morning plan.</div>
                <button class="chief-action-btn" onclick="generateAfternoonCheckin()">Trigger Check-in</button>
            </div>
        `;
        return;
    }

    body.innerHTML = `
        <div style="font-size: 0.85rem; color: var(--text-primary); line-height: 1.5; margin-bottom: 16px;">
            <strong>Analysis:</strong> ${checkin.progress_summary}
        </div>
        <div style="font-size:0.75rem; text-transform:uppercase; color:var(--gold); font-weight:600; margin-bottom:10px; letter-spacing:0.05em;">Key Check-in Questions</div>
        <div class="chief-list">
            ${(checkin.questions || []).map((q, idx) => `
                <div class="chief-list-item">
                    <span class="chief-list-num">${idx + 1}.</span>
                    <span>${q}</span>
                </div>
            `).join('')}
        </div>
    `;
}

function renderNightDebrief() {
    const debrief = _chiefState.night_debrief;
    const body = document.getElementById('chiefDebriefBody');
    const checkin = _chiefState.afternoon_checkin;
    if (!body) return;

    if (!checkin) {
        body.innerHTML = `<div class="empty-state-sm">Waiting for Afternoon Check-in before debriefing.</div>`;
        return;
    }

    // If debrief has not run, show questions input form
    if (!debrief) {
        const questions = checkin.questions || ["How would you rate today's outcomes?"];
        body.innerHTML = `
            <div style="margin-bottom:16px; font-size:0.85rem; color:var(--text-secondary);">
                Answer today's check-in questions to archive outcomes and generate tomorrow's priorities.
            </div>
            <div id="debriefQuestionsForm" style="display:flex; flex-direction:column; gap:16px;">
                ${questions.map((q, idx) => `
                    <div class="chief-checkin-q">
                        <div class="chief-q-label">Question ${idx + 1}: ${q}</div>
                        <input type="text" class="chief-q-input" data-q="${q}" placeholder="Type your response here...">
                    </div>
                `).join('')}
                <button class="chief-action-btn" onclick="finalizeNightDebrief()" style="align-self:flex-start;">Finalize & Archive</button>
            </div>
        `;
        return;
    }

    // Debrief complete: render review
    body.innerHTML = `
        <div class="chief-briefing-header">
            <div class="chief-greeting">Debrief Completed Successfully</div>
        </div>
        <div class="chief-mission-container" style="border-left-color: var(--status-ok);">
            <div class="chief-mission-label">Executive Outcome Review</div>
            <div class="chief-mission-text" style="font-weight: normal; font-size: 0.9rem; line-height: 1.5;">${debrief.review_text}</div>
        </div>
        <div style="margin-top:20px;">
            <div style="font-size:0.75rem; text-transform:uppercase; color:var(--gold); font-weight:600; margin-bottom:10px; letter-spacing:0.05em;">Tomorrow's Draft Priorities</div>
            <div class="chief-list">
                ${(debrief.tomorrow_priorities || []).map((p, idx) => `
                    <div class="chief-list-item">
                        <span class="chief-list-num">${idx + 1}.</span>
                        <span>${p}</span>
                    </div>
                `).join('')}
            </div>
        </div>
    `;
}

function renderExecutiveInsights() {
    const container = document.getElementById('chiefInsightsBody');
    if (!container) return;

    const debrief = _chiefState.night_debrief;
    const hasDebrief = !!debrief;

    container.innerHTML = `
        <div class="chief-insights-container">
            <div class="chief-insight-group">
                <div class="chief-insight-title">Effort vs ROI Target</div>
                <div class="chief-insight-desc">
                    ${hasDebrief 
                        ? "Evaluation score processed. Focus on high-leverage outputs (Fifth Veda tutorials, direct sales outreach) is generating 3x standard returns." 
                        : "Waiting for evening debrief to compute ROI metrics."}
                </div>
            </div>
            <div class="chief-insight-group">
                <div class="chief-insight-title">Strategic Recommendation</div>
                <div class="chief-insight-desc">
                    ${hasDebrief
                        ? "Mitigate administrative overhead. Delegate low-value tasks using automated pipelines to maintain a 90+ execution level."
                        : "Morning assessment recommends prioritization of critical tasks to avoid end-of-day pressure."}
                </div>
            </div>
        </div>
    `;
}

function updateExecutionScore() {
    const valText = document.getElementById('chiefScoreValue');
    const progressCircle = document.getElementById('chiefScoreProgressCircle');
    if (!valText || !progressCircle) return;

    // ── 1. Calculate Deterministic Score in Frontend ──
    const habits = _chiefState.habits || {};
    const totalHabits = Object.keys(habits).length;
    const completedHabits = Object.values(habits).filter(v => v === true).length;
    const scoreHabits = totalHabits > 0 ? (completedHabits / totalHabits) * 20.0 : 0.0;

    const highTasks = _chiefTasks.filter(t => t.priority === "high");
    const completedHigh = highTasks.filter(t => t.done === true);
    const scoreCritical = highTasks.length > 0 ? (completedHigh.length / highTasks.length) * 30.0 : 30.0;

    const completedTasks = _chiefTasks.filter(t => t.done === true);
    const scoreDeadlines = _chiefTasks.length > 0 ? (completedTasks.length / _chiefTasks.length) * 20.0 : 20.0;

    const scoreRevenue = habits["Revenue Update"] === true ? 15.0 : 0.0;

    const hasDebrief = !!_chiefState.night_debrief;
    const scoreReview = hasDebrief ? 15.0 : 0.0;

    const finalScore = Math.round(scoreCritical + scoreHabits + scoreDeadlines + scoreRevenue + scoreReview);

    valText.textContent = finalScore;

    // SVG dash offset calculation
    // R=50, C=2*pi*r = 314
    const circumference = 314;
    const offset = circumference - (finalScore / 100) * circumference;
    progressCircle.style.strokeDasharray = `${circumference}`;
    progressCircle.style.strokeDashoffset = `${offset}`;
}

// ── HANDLERS ──

async function generateMorningBrief() {
    const today = getLocalDateStr();
    showLoader(true, "Preparing JATAYU Morning Assessment...");
    try {
        const res = await fetch('/api/chief/morning-brief', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({date: today})
        });
        const state = await res.json();
        _chiefState = state;
        renderMorningBrief();
        renderAfternoonCheckin();
        renderNightDebrief();
        updateExecutionScore();
        renderExecutiveInsights();
    } catch (e) {
        console.error("Failed to generate morning brief", e);
    } finally {
        showLoader(false);
    }
}

async function generateAfternoonCheckin() {
    const today = getLocalDateStr();
    showLoader(true, "Formulating Afternoon Check-in...");
    try {
        const res = await fetch('/api/chief/afternoon-checkin', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({date: today})
        });
        const state = await res.json();
        _chiefState = state;
        renderAfternoonCheckin();
        renderNightDebrief();
        updateExecutionScore();
    } catch (e) {
        console.error("Failed to generate check-in", e);
    } finally {
        showLoader(false);
    }
}

async function toggleHabit(name) {
    const today = getLocalDateStr();
    try {
        const res = await fetch('/api/chief/habit/toggle', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({date: today, habit: name})
        });
        const state = await res.json();
        _chiefState = state;
        renderHabits();
        updateExecutionScore();
    } catch (e) {
        console.error("Failed to toggle habit", e);
    }
}

async function finalizeNightDebrief() {
    const today = getLocalDateStr();
    const form = document.getElementById('debriefQuestionsForm');
    if (!form) return;

    const answers = {};
    form.querySelectorAll('input.chief-q-input').forEach(input => {
        answers[input.dataset.q] = input.value || "Completed successfully.";
    });

    showLoader(true, "Archiving outcomes & generating recommendations...");
    try {
        const res = await fetch('/api/chief/night-debrief', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({date: today, answers: answers})
        });
        const state = await res.json();
        _chiefState = state;
        renderNightDebrief();
        updateExecutionScore();
        renderExecutiveInsights();
    } catch (e) {
        console.error("Failed to finalize debrief", e);
    } finally {
        showLoader(false);
    }
}
