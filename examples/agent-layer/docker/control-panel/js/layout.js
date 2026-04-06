/**
 * Gemeinsames Sidebar Layout für alle Control Panel Seiten
 * Wird auf allen geschützten Seiten eingebunden
 */

function initControlPanel(currentPage) {
    // Zuerst Auth prüfen
    requireAuth();

    // Injecte Styles
    if (!document.getElementById('layout-styles')) {
        document.head.insertAdjacentHTML('beforeend', `
        <style id="layout-styles">
        :root {
            --sidebar-width: 260px;
        }
        
        * { box-sizing: border-box; margin: 0; padding: 0; }
        
        body {
            margin-left: var(--sidebar-width);
            padding: 1.5rem 2rem;
        }
        
        .sidebar {
            width: var(--sidebar-width);
            background: var(--panel);
            border-right: 1px solid var(--border);
            position: fixed;
            top: 0;
            left: 0;
            bottom: 0;
            padding: 1rem 0;
            z-index: 100;
        }
        
        .sidebar-header {
            padding: 0 1.25rem 1rem;
            border-bottom: 1px solid var(--border);
            margin-bottom: 0.5rem;
        }
        
        .sidebar-header h2 {
            font-size: 1.1rem;
            font-weight: 600;
        }
        
        .sidebar-nav a {
            display: block;
            padding: 0.75rem 1.25rem;
            color: var(--text);
            text-decoration: none;
            border-left: 3px solid transparent;
            transition: background 0.15s;
        }
        
        .sidebar-nav a:hover {
            background: rgba(91, 159, 212, 0.08);
        }
        
        .sidebar-nav a.active {
            background: rgba(91, 159, 212, 0.12);
            border-left-color: var(--accent);
            color: var(--accent);
        }
        
        .sidebar-footer {
            position: absolute;
            bottom: 0;
            left: 0;
            right: 0;
            padding: 1rem 1.25rem;
            border-top: 1px solid var(--border);
        }
        
        .page-header {
            margin-bottom: 1.5rem;
        }
        
        .page-header h1 {
            font-size: 1.4rem;
            font-weight: 600;
            margin-bottom: 0.25rem;
        }
        
        .page-header p {
            color: var(--muted);
            font-size: 0.9rem;
        }
        
        .logout-btn {
            width: 100%;
            background: var(--border);
            color: var(--text);
            margin-top: 0.75rem;
        }
        
        .logout-btn:hover {
            background: var(--err);
            color: white;
        }
        </style>
        `);
    }

    const user = getCurrentUser();

    // Injecte Sidebar
    document.body.insertAdjacentHTML('afterbegin', `
    <div class="sidebar">
        <div class="sidebar-header">
            <h2>⚙️ Control Panel</h2>
        </div>

        <nav class="sidebar-nav">
            <a href="dashboard.html" ${currentPage === 'dashboard' ? 'class="active"' : ''}>📊 Dashboard</a>
            <a href="agents.html" ${currentPage === 'agents' ? 'class="active"' : ''}>🤖 Agents</a>
            <a href="workflows.html" ${currentPage === 'workflows' ? 'class="active"' : ''}>⚡ Workflows</a>
            <a href="tools.html" ${currentPage === 'tools' ? 'class="active"' : ''}>🔧 Tools</a>
            <a href="users.html" ${currentPage === 'users' ? 'class="active"' : ''}>👤 Benutzer</a>
        </nav>

        <div class="sidebar-footer">
            <div>
                <strong>${user.email}</strong><br>
                <span style="color: var(--muted); font-size: 0.8rem;">${user.role}</span>
            </div>
            <button class="logout-btn" onclick="logout()">Abmelden</button>
        </div>
    </div>
    `);
}