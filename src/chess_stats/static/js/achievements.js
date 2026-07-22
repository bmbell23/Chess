(() => {
    const PLAYER = document.querySelector('meta[name="player"]')?.content || '';
    const pq = PLAYER ? `?player=${encodeURIComponent(PLAYER)}` : '';
    let data = null;
    let activeCat = 'All';

    const load = async () => {
        const resp = await fetch(`/api/v1/achievements${pq}`);
        if (!resp.ok) return;
        data = await resp.json();
        render();
    };

    function render() {
        if (!data || !data.available) {
            document.getElementById('ach-grid').innerHTML =
                '<p class="mode-sub">No data yet — sync this player first.</p>';
            return;
        }
        document.getElementById('score').textContent = data.score.toLocaleString();
        document.getElementById('score-sub').textContent =
            `${data.earned_count} of ${data.total_count} unlocked · ${data.max_score.toLocaleString()} max`;

        if (data.first_run && data.newly_unlocked.length) {
            const r = document.getElementById('recap');
            r.hidden = false;
            r.innerHTML = `🎉 <strong>You earned ${data.newly_unlocked.length} achievements — ` +
                `${data.score.toLocaleString()} points!</strong> Welcome to the wall of fame.`;
        }

        const cats = ['All', ...Object.keys(data.categories)];
        document.getElementById('cat-filter').innerHTML = cats.map((c) => {
            const meta = c === 'All'
                ? `${data.earned_count}/${data.total_count}`
                : `${data.categories[c].earned}/${data.categories[c].total}`;
            return `<button class="frame-btn ${c === activeCat ? 'active' : ''}" data-cat="${c}">${c} <span class="cat-meta">${meta}</span></button>`;
        }).join('');
        document.getElementById('cat-filter').onclick = (e) => {
            const b = e.target.closest('.frame-btn');
            if (!b) return;
            activeCat = b.dataset.cat;
            render();
        };

        const shown = data.achievements.filter((a) => activeCat === 'All' || a.category === activeCat);
        // earned first, then within each group in ladder order:
        // category → metric → tier ascending (so Brilliant I, II, III… read top-down)
        shown.sort((a, b) =>
            (b.earned - a.earned) ||
            a.category.localeCompare(b.category) ||
            a.metric.localeCompare(b.metric) ||
            (a.threshold - b.threshold));
        document.getElementById('ach-grid').innerHTML =
            `<div class="ach-cards">` + shown.map(card).join('') + `</div>`;
    }

    function card(a) {
        const pct = Math.round(a.progress * 100);
        const bar = a.earned ? '' :
            `<div class="ach-bar"><div class="ach-bar-fill" style="width:${pct}%"></div></div>` +
            `<div class="ach-prog">${a.value.toLocaleString()} / ${a.threshold.toLocaleString()}</div>`;
        return `<div class="ach-card ${a.earned ? 'earned' : 'locked'}">
            <div class="ach-icon">${a.icon}</div>
            <div class="ach-body">
                <div class="ach-name">${a.name}</div>
                <div class="ach-desc">${a.description}</div>
                ${bar}
            </div>
            <div class="ach-pts">${a.points}</div>
        </div>`;
    }

    load();
})();
