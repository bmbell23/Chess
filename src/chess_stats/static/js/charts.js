/* Renders the overview charts from /api/v1/charts/*. Chart.js is vendored. */
(() => {
    if (typeof Chart === 'undefined') return;

    const TEXT = '#9aa3af';
    const GRID = 'rgba(154,163,175,0.15)';
    Chart.defaults.color = TEXT;
    Chart.defaults.borderColor = GRID;
    Chart.defaults.font.family = 'system-ui, sans-serif';

    const MODE_COLORS = {
        rapid: '#81b64c',   // chess.com green
        blitz: '#ff9f1c',   // lightning/fire orange
        bullet: '#8e9297',  // gunmetal gray
        daily: '#fff3a0',   // pale sun white-yellow
    };
    const WLD_COLORS = { win: '#81b64c', draw: '#96928f', loss: '#fa412d' };

    const PLAYER = document.querySelector('meta[name="player"]')?.content || '';

    const get = async (path) => {
        const url = PLAYER
            ? `${path}${path.includes('?') ? '&' : '?'}player=${encodeURIComponent(PLAYER)}`
            : path;
        const resp = await fetch(url);
        if (!resp.ok) throw new Error(`${url} → ${resp.status}`);
        return resp.json();
    };

    // API timestamps are naive UTC — append Z so the browser localizes them
    const toMs = (iso) => new Date(iso + 'Z').getTime();
    const shortDate = (ms) =>
        new Date(ms).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });

    async function ratingChart() {
        const series = await get('/api/v1/charts/rating-history');
        const datasets = Object.entries(series)
            .filter(([, pts]) => pts.length)
            .map(([mode, pts]) => ({
                label: mode,
                data: pts.map((p) => ({ x: toMs(p.t), y: p.r })),
                borderColor: MODE_COLORS[mode],
                backgroundColor: MODE_COLORS[mode],
                pointRadius: 1.5,
                borderWidth: 2,
                // monotone: smooth but can never overshoot backwards/vertically
                // (bezier tension caused visible loops at dense clusters — #14)
                cubicInterpolationMode: 'monotone',
            }));
        new Chart(document.getElementById('chart-rating'), {
            type: 'line',
            data: { datasets },
            options: {
                scales: {
                    x: {
                        // linear scale on epoch ms = real time axis; all modes
                        // share it and overlap by date (no adapter needed)
                        type: 'linear',
                        ticks: {
                            maxTicksLimit: 8,
                            callback: (v) => shortDate(v),
                        },
                        title: { display: false },
                    },
                    y: { title: { display: true, text: 'rating' } },
                },
                plugins: {
                    tooltip: {
                        callbacks: {
                            title: (items) =>
                                new Date(items[0].parsed.x).toLocaleString(undefined, {
                                    month: 'short',
                                    day: 'numeric',
                                    hour: '2-digit',
                                    minute: '2-digit',
                                }),
                        },
                    },
                },
            },
        });
    }

    async function wldCharts() {
        const wld = await get('/api/v1/charts/wld');
        const modes = Object.keys(wld.by_mode).filter(
            (m) => wld.by_mode[m].win + wld.by_mode[m].loss + wld.by_mode[m].draw > 0
        );
        const totals = Object.fromEntries(
            modes.map((m) => [
                m,
                wld.by_mode[m].win + wld.by_mode[m].draw + wld.by_mode[m].loss,
            ])
        );
        new Chart(document.getElementById('chart-wld'), {
            type: 'bar',
            data: {
                labels: modes,
                datasets: ['win', 'draw', 'loss'].map((k) => ({
                    label: k,
                    // 100%-stacked: normalized so modes are comparable
                    data: modes.map((m) => (100 * wld.by_mode[m][k]) / totals[m]),
                    backgroundColor: WLD_COLORS[k],
                })),
            },
            options: {
                scales: {
                    x: { stacked: true },
                    y: {
                        stacked: true,
                        min: 0,
                        max: 100,
                        ticks: { callback: (v) => v + '%' },
                    },
                },
                plugins: {
                    tooltip: {
                        callbacks: {
                            label: (item) => {
                                const mode = modes[item.dataIndex];
                                const count = wld.by_mode[mode][item.dataset.label];
                                return `${item.dataset.label}: ${item.parsed.y.toFixed(1)}% (${count} of ${totals[mode]} games)`;
                            },
                        },
                    },
                },
            },
        });
    }

    async function openingsChart() {
        const rows = await get('/api/v1/charts/openings?limit=10');
        new Chart(document.getElementById('chart-openings'), {
            type: 'bar',
            data: {
                labels: rows.map((r) => `${r.eco} ${r.name ?? ''}`.slice(0, 32)),
                datasets: ['win', 'draw', 'loss'].map((k) => ({
                    label: k,
                    data: rows.map((r) => r[k]),
                    backgroundColor: WLD_COLORS[k],
                })),
            },
            options: {
                indexAxis: 'y',
                scales: { x: { stacked: true }, y: { stacked: true } },
                plugins: {
                    tooltip: {
                        callbacks: {
                            afterTitle: (items) => `win rate ${rows[items[0].dataIndex].winrate}%`,
                        },
                    },
                },
            },
        });
    }

    async function timeCharts() {
        const data = await get('/api/v1/charts/time-buckets');
        const active = data.hours.filter((h) => h.games > 0);
        new Chart(document.getElementById('chart-hours'), {
            type: 'bar',
            data: {
                labels: active.map((h) => `${h.hour}:00`),
                datasets: [
                    {
                        label: 'win rate %',
                        data: active.map((h) => h.winrate),
                        backgroundColor: MODE_COLORS.rapid,
                    },
                ],
            },
            options: {
                scales: { y: { min: 0, max: 100, title: { display: true, text: '%' } } },
                plugins: {
                    tooltip: {
                        callbacks: {
                            afterLabel: (item) => `${active[item.dataIndex].games} games`,
                        },
                    },
                },
            },
        });
        new Chart(document.getElementById('chart-weekdays'), {
            type: 'bar',
            data: {
                labels: data.weekdays.map((d) => d.day),
                datasets: [
                    {
                        label: 'win rate %',
                        data: data.weekdays.map((d) => d.winrate),
                        backgroundColor: MODE_COLORS.daily,
                    },
                ],
            },
            options: {
                scales: { y: { min: 0, max: 100, title: { display: true, text: '%' } } },
                plugins: {
                    tooltip: {
                        callbacks: {
                            afterLabel: (item) => `${data.weekdays[item.dataIndex].games} games`,
                        },
                    },
                },
            },
        });
    }

    const QUALITY_COLORS = {
        brilliant: '#26c2a3',
        great: '#5c8bb0',
        best: '#81b64c',
        excellent: '#a8c26a',
        good: '#cdd0a5',
        inaccuracy: '#f7c045',
        mistake: '#ff9f5a',
        blunder: '#fa412d',
    };

    let qualityChartInstance = null;

    async function qualityChart() {
        const data = await get('/api/v1/charts/move-quality');
        const meta = document.getElementById('quality-meta');
        const btn = document.getElementById('analyze-btn');
        meta.textContent = `— ${data.analyzed_games} of ${data.total_games} games analyzed`;
        btn.hidden = data.analyzed_games >= data.total_games;

        if (data.analyzed_games > 0) {
            const datasets = Object.entries(data.classes).map(([cls, pts]) => ({
                label: cls,
                data: pts.map((p) => ({ x: toMs(p.t), y: p.v })),
                borderColor: QUALITY_COLORS[cls],
                backgroundColor: QUALITY_COLORS[cls],
                pointRadius: 0,
                borderWidth: 2,
                cubicInterpolationMode: 'monotone',
            }));
            if (qualityChartInstance) qualityChartInstance.destroy();
            qualityChartInstance = new Chart(document.getElementById('chart-quality'), {
                type: 'line',
                data: { datasets },
                options: {
                    scales: {
                        x: {
                            type: 'linear',
                            ticks: { maxTicksLimit: 8, callback: (v) => shortDate(v) },
                        },
                        y: { title: { display: true, text: 'cumulative moves' } },
                    },
                    plugins: {
                        tooltip: {
                            callbacks: {
                                title: (items) => shortDate(items[0].parsed.x),
                            },
                        },
                    },
                },
            });
        }
    }

    const analyzeBtn = document.getElementById('analyze-btn');
    if (analyzeBtn) {
        analyzeBtn.addEventListener('click', async () => {
            analyzeBtn.disabled = true;
            analyzeBtn.textContent = 'Analyzing…';
            const q = PLAYER ? `?player=${encodeURIComponent(PLAYER)}` : '';
            const start = await fetch(`/api/v1/analysis${q}`, { method: 'POST' });
            if (!start.ok) {
                analyzeBtn.textContent = 'Analysis unavailable';
                return;
            }
            const poll = setInterval(async () => {
                try {
                    const p = await (await fetch(`/api/v1/analysis/progress${q}`)).json();
                    if (p.state === 'error') {
                        clearInterval(poll);
                        analyzeBtn.textContent = 'Analysis failed — retry';
                        analyzeBtn.disabled = false;
                    } else if (p.state === 'done') {
                        clearInterval(poll);
                        analyzeBtn.textContent = 'Analyze games';
                        analyzeBtn.disabled = false;
                        qualityChart();
                    } else if (p.total) {
                        analyzeBtn.textContent = `Analyzing… ${p.done ?? 0}/${p.total}`;
                        if ((p.done ?? 0) % 25 === 0) qualityChart();
                    }
                } catch (err) {
                    console.error(err);
                }
            }, 2000);
        });
    }

    function tile(label, value, sub, tone) {
        return `<div class="tile ${tone ?? ''}"><div class="t-label">${label}</div>` +
               `<div class="t-value">${value ?? '—'}</div>` +
               `<div class="t-sub">${sub ?? ''}</div></div>`;
    }

    async function insightsSection() {
        const d = await get('/api/v1/insights');
        const el = document.getElementById('insight-tiles');
        const r = d.records, t = d.tilt, p = d.performance, x = d.terminations;
        const cur = r.streaks_overall.current;
        const tiles = [
            tile('Current streak',
                cur.length ? `${cur.length} ${cur.kind}${cur.length > 1 ? 's' : ''}` : '0',
                'all modes', cur.kind === 'win' ? 't-good' : cur.kind === 'loss' ? 't-bad' : ''),
            tile('Longest win streak', r.streaks_overall.longest_win, 'all modes', 't-good'),
            tile('Longest skid', r.streaks_overall.longest_loss, 'all modes', 't-bad'),
            tile('Biggest upset', r.biggest_upset ? `+${r.biggest_upset.gap}` : null,
                r.biggest_upset ? `beat ${r.biggest_upset.opponent} (${r.biggest_upset.opponent_rating})` : '', 't-good'),
            tile('Fastest mate', r.fastest_mate_moves ? `${r.fastest_mate_moves} moves` : null, 'delivered by you'),
            tile('Longest game', r.longest_game_moves ? `${r.longest_game_moves} moves` : null, ''),
            tile('Best month', r.best_month ? r.best_month.month : null,
                r.best_month ? `${r.best_month.win}W-${r.best_month.loss}L-${r.best_month.draw}D` : ''),
            tile('After a win', t.after_win.winrate != null ? `${t.after_win.winrate}%` : null,
                `win rate · ${t.after_win.games} games`),
            tile('After a loss', t.after_loss.winrate != null ? `${t.after_loss.winrate}%` : null,
                `win rate · ${t.after_loss.games} games`,
                t.after_loss.winrate < t.after_win.winrate - 5 ? 't-bad' : ''),
            tile('Revenge games', t.revenge.winrate != null ? `${t.revenge.winrate}%` : null,
                `rematch <5min after a loss · ${t.revenge.games}`),
            tile('Vs expectations', p.overperformance > 0 ? `+${p.overperformance}` : p.overperformance,
                `wins above Elo expectation (${p.games} rated)`,
                p.overperformance >= 0 ? 't-good' : 't-bad'),
            tile('Flagged losses', x.flagged_loss_pct != null ? `${x.flagged_loss_pct}%` : null,
                'of live losses were on time', x.flagged_loss_pct > 25 ? 't-bad' : ''),
        ];
        el.innerHTML = tiles.join('');

        const rivalRow = (e, keyField, cls) =>
            `<div class="rival-row"><span class="r-name">${e.opponent}</span>` +
            `<span class="r-rec"><span class="r-key ${cls}">${e[keyField]}</span>` +
            ` · ${e.win}W-${e.loss}L-${e.draw}D · ${e.modes.join('/')}</span></div>`;
        const lists = [];
        if (d.rivals?.nemeses?.length) {
            lists.push(
                `<div class="rival-list"><h3>Nemesis — they beat you the most</h3>` +
                d.rivals.nemeses.map((e) => rivalRow(e, 'loss', 'bad')).join('') + `</div>`
            );
        }
        if (d.rivals?.dominees?.length) {
            lists.push(
                `<div class="rival-list"><h3>Most defeated — you beat them the most</h3>` +
                d.rivals.dominees.map((e) => rivalRow(e, 'win', 'good')).join('') + `</div>`
            );
        }
        document.getElementById('rival-lists').innerHTML = lists.join('');

        new Chart(document.getElementById('chart-fatigue'), {
            type: 'bar',
            data: {
                labels: t.fatigue_curve.map((b) =>
                    b.game_in_session === 8 ? '8+' : String(b.game_in_session)),
                datasets: [{
                    label: 'win rate %',
                    data: t.fatigue_curve.map((b) => b.winrate),
                    backgroundColor: MODE_COLORS.blitz,
                }],
            },
            options: {
                scales: { y: { min: 0, max: 100, title: { display: true, text: '%' } } },
                plugins: { tooltip: { callbacks: {
                    afterLabel: (i) => `${t.fatigue_curve[i.dataIndex].games} games`,
                } } },
            },
        });
        new Chart(document.getElementById('chart-gap'), {
            type: 'bar',
            data: {
                labels: p.vs_rating_gap.map((b) => b.label),
                datasets: [{
                    label: 'win rate %',
                    data: p.vs_rating_gap.map((b) => b.winrate),
                    backgroundColor: MODE_COLORS.rapid,
                }],
            },
            options: {
                scales: {
                    y: { min: 0, max: 100, title: { display: true, text: '%' } },
                    x: { title: { display: true, text: 'opponent rating − yours' } },
                },
                plugins: { tooltip: { callbacks: {
                    afterLabel: (i) => `${p.vs_rating_gap[i.dataIndex].games} games`,
                } } },
            },
        });
    }

    Promise.allSettled([ratingChart(), wldCharts(), openingsChart(), timeCharts(), qualityChart(), insightsSection()]).then(
        (results) =>
            results
                .filter((r) => r.status === 'rejected')
                .forEach((r) => console.error('chart failed:', r.reason))
    );
})();
