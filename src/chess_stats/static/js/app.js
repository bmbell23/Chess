const syncBtn = document.getElementById('sync-btn');

if (syncBtn) {
    syncBtn.addEventListener('click', async () => {
        syncBtn.disabled = true;
        syncBtn.textContent = 'Syncing…';
        try {
            const resp = await fetch('/api/v1/sync', { method: 'POST' });
            if (!resp.ok) throw new Error(`sync failed: ${resp.status}`);
            const result = await resp.json();
            syncBtn.textContent = `+${result.games_added} games`;
            setTimeout(() => window.location.reload(), 900);
        } catch (err) {
            console.error(err);
            syncBtn.textContent = 'Sync failed — retry';
            syncBtn.disabled = false;
        }
    });
}
