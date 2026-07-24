'use strict';

const INTEGRATIONS_MAP = {
    'Knowledge': [
        {name:'Obsidian',icon:'💎',id:'obsidian'},{name:'Notion',icon:'📝',id:'notion'},{name:'Evernote',icon:'🐘',id:'evernote'},
    ],
    'Communication': [
        {name:'WhatsApp',icon:'💬',id:'whatsapp'},{name:'Discord',icon:'🎮',id:'discord'},
        {name:'Slack',icon:'💼',id:'slack'},{name:'Telegram',icon:'✈️',id:'telegram'},
    ],
    'Social': [
        {name:'LinkedIn',icon:'🔗',id:'linkedin'},{name:'Instagram',icon:'📸',id:'instagram'},
        {name:'X',icon:'𝕏',id:'x'},{name:'YouTube',icon:'▶️',id:'youtube'},
    ],
    'Development': [
        {name:'GitHub',icon:'🐙',id:'github'},{name:'VS Code',icon:'💻',id:'vscode'},{name:'Docker',icon:'🐳',id:'docker'},
    ],
};

async function loadIntegrations() {
    const container = document.getElementById('intGrid');
    if (!container) return;
    
    let html = '';
    
    // --- Google Accounts Section ---
    let accountCount = 0;
    let accountsHtml = '';
    
    try {
        const response = await fetch('/api/integrations/google/accounts');
        const data = await response.json();
        const accounts = data.accounts || [];
        accountCount = accounts.length;
        
        if (accounts.length === 0) {
            accountsHtml += `<div style="color:var(--text-muted); font-size:0.85rem; padding: 10px 0;">No Google accounts connected yet.</div>`;
        } else {
            for (const acct of accounts) {
                // Render service pills from capability flags dict
                const services = acct.services || {};
                let servicesHtml = '';
                if (typeof services === 'object' && !Array.isArray(services)) {
                    servicesHtml = Object.entries(services)
                        .filter(([k, v]) => v)
                        .map(([k]) => `<span class="service-pill">${k.charAt(0).toUpperCase() + k.slice(1)}</span>`)
                        .join('');
                } else if (Array.isArray(services)) {
                    servicesHtml = services.map(s => `<span class="service-pill">${s}</span>`).join('');
                }
                
                const defaultBadge = acct.is_default 
                    ? `<span class="default-badge">⭐ DEFAULT</span>` 
                    : `<button class="set-default-btn" onclick="setDefaultGoogleAccount('${acct.email}')">Set Default</button>`;
                
                const needsReauth = acct.status === 'Needs Reauth';
                const reauthBanner = needsReauth 
                    ? `<div class="reauth-banner" onclick="window.location.href='/api/integrations/google/auth'">⚠️ New Workspace features require one-time re-authorization. Click to update.</div>`
                    : '';
                
                const connectedDate = acct.connected_date 
                    ? new Date(acct.connected_date).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
                    : '';
                
                const lastUsed = acct.last_used
                    ? `Last used: ${_timeAgo(acct.last_used)}`
                    : '';
                
                const metaLine = [connectedDate ? `Connected ${connectedDate}` : '', lastUsed].filter(Boolean).join(' · ');
                
                accountsHtml += `
                <div class="google-account-card" data-status="${needsReauth ? 'needs-reauth' : 'connected'}">
                    <div class="google-account-left">
                        <img src="${acct.picture}" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' width=\\'44\\' height=\\'44\\'><rect width=\\'44\\' height=\\'44\\' rx=\\'22\\' fill=\\'%23333\\'/><text x=\\'50%\\' y=\\'54%\\' font-size=\\'20\\' fill=\\'white\\' dominant-baseline=\\'middle\\' text-anchor=\\'middle\\'>${acct.name ? acct.name[0].toUpperCase() : 'G'}</text></svg>'" class="google-account-avatar" />
                        <div class="google-account-info">
                            <div class="google-account-alias">
                                <span class="alias-text" id="alias-${acct.email}">${escapeHtml(acct.alias || acct.name)}</span>
                                <button class="alias-edit-btn" onclick="editGoogleAlias('${acct.email}')" title="Edit alias">✏️</button>
                            </div>
                            <div class="google-account-email">${acct.email}</div>
                            ${metaLine ? `<div class="google-account-meta">${metaLine}</div>` : ''}
                        </div>
                    </div>
                    <div class="google-account-right">
                        <div class="google-account-services">${servicesHtml}</div>
                        ${defaultBadge}
                        <button class="disconnect-btn" onclick="disconnectGoogleAccount('${acct.email}')" title="Disconnect">✕</button>
                    </div>
                    ${reauthBanner}
                </div>`;
            }
        }
    } catch(e) {
        console.error("Failed to load Google accounts:", e);
        accountsHtml += `<div style="color:var(--status-danger); font-size:0.85rem; padding: 10px 0;">Error loading Google accounts.</div>`;
    }
    
    html += `<div class="int-category">
        <div class="int-category-title" style="display:flex; justify-content:space-between; align-items:center;">
            <span>Google Workspace${accountCount > 0 ? ` (${accountCount})` : ''}</span>
            <button class="dash-action-btn" onclick="window.location.href='/api/integrations/google/auth'" style="padding: 6px 12px; font-size: 0.75rem; flex-direction:row; gap:8px;">
                <span class="int-card-icon" style="font-size:1rem;">G</span> Connect Account
            </button>
        </div>
        <div class="google-accounts-list">${accountsHtml}</div>
    </div>`;

    // --- Other Integrations ---
    let connectedIds = new Set();
    try {
        const [plugins, creds] = await Promise.all([
            fetch('/api/plugins').then(r=>r.json()).catch(()=>({})),
            fetch('/api/credentials').then(r=>r.json()).catch(()=>({})),
        ]);
        if (plugins) Object.keys(plugins).forEach(k=>connectedIds.add(k.toLowerCase()));
        if (creds) Object.keys(creds).forEach(k=>connectedIds.add(k.toLowerCase()));
    } catch(e){}
    
    for (const [category, items] of Object.entries(INTEGRATIONS_MAP)) {
        html += `<div class="int-category"><div class="int-category-title">${category}</div><div class="int-grid">`;
        for (const item of items) {
            const status = connectedIds.has(item.id) ? 'connected' : 'not-connected';
            html += `<div class="int-card" data-status="${status}" data-id="${item.id}">
                        <div class="int-card-icon">${item.icon}</div>
                        <div class="int-card-name">${item.name}</div>
                        <div class="int-status-dot"></div>
                     </div>`;
        }
        html += `</div></div>`;
    }
    container.innerHTML = html;
}

// ── Google Account Actions ──

window.setDefaultGoogleAccount = async function(email) {
    try {
        const response = await fetch(`/api/integrations/google/accounts/${encodeURIComponent(email)}/default`, {
            method: 'POST'
        });
        if (response.ok) {
            loadIntegrations();
        } else {
            console.error("Failed to set default account");
        }
    } catch(e) {
        console.error(e);
    }
}

window.disconnectGoogleAccount = async function(email) {
    if (!confirm(`Disconnect ${email}?\n\nThis will remove all stored tokens for this account. You can reconnect later.`)) {
        return;
    }
    try {
        const response = await fetch(`/api/integrations/google/accounts/${encodeURIComponent(email)}`, {
            method: 'DELETE'
        });
        if (response.ok) {
            loadIntegrations();
        } else {
            alert("Failed to disconnect account.");
        }
    } catch(e) {
        console.error(e);
        alert("Error disconnecting account.");
    }
}

window.editGoogleAlias = async function(email) {
    const aliasEl = document.getElementById(`alias-${email}`);
    if (!aliasEl) return;
    
    const currentAlias = aliasEl.textContent;
    const newAlias = prompt("Set alias for this account:", currentAlias);
    
    if (newAlias === null || newAlias.trim() === '' || newAlias.trim() === currentAlias) return;
    
    try {
        const response = await fetch(`/api/integrations/google/accounts/${encodeURIComponent(email)}/alias`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ alias: newAlias.trim() })
        });
        if (response.ok) {
            loadIntegrations();
        } else {
            alert("Failed to update alias.");
        }
    } catch(e) {
        console.error(e);
    }
}

function _timeAgo(isoString) {
    const now = new Date();
    const then = new Date(isoString);
    const diffMs = now - then;
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 1) return 'just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours}h ago`;
    const diffDays = Math.floor(diffHours / 24);
    if (diffDays < 7) return `${diffDays}d ago`;
    return then.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
