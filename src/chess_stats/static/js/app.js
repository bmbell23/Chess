const PLAYER = document.querySelector('meta[name="player"]')?.content || '';
const PQ = PLAYER ? `?player=${encodeURIComponent(PLAYER)}` : '';

const syncBtn = document.getElementById('sync-btn');

if (syncBtn) {
    syncBtn.addEventListener('click', async () => {
        syncBtn.disabled = true;
        syncBtn.textContent = 'Syncing…';
        try {
            const resp = await fetch(`/api/v1/sync${PQ}`, { method: 'POST' });
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

// First visit for an unsynced player: kick off a background sync and poll progress.
const firstSync = document.getElementById('first-sync');

if (firstSync) {
    const text = document.getElementById('first-sync-text');
    const name = firstSync.dataset.player;
    const q = `?player=${encodeURIComponent(name)}`;

    (async () => {
        const start = await fetch(`/api/v1/sync${q}&background=true`, { method: 'POST' });
        if (!start.ok) {
            text.textContent = `Could not start sync (${start.status}).`;
            return;
        }
        const poll = setInterval(async () => {
            try {
                const p = await (await fetch(`/api/v1/sync/progress${q}`)).json();
                if (p.state === 'error') {
                    clearInterval(poll);
                    text.textContent = p.error?.includes('404')
                        ? `chess.com user “${name}” not found.`
                        : `Sync failed: ${p.error}`;
                } else if (p.state === 'done') {
                    clearInterval(poll);
                    text.textContent = 'Done — loading charts…';
                    window.location.reload();
                } else if (p.months_total) {
                    text.innerHTML = `Syncing <strong>${name}</strong>: ` +
                        `${p.months_done ?? 0} of ${p.months_total} months · ` +
                        `${p.games ?? 0} games so far`;
                }
            } catch (err) {
                console.error(err);
            }
        }, 1500);
    })();
}
