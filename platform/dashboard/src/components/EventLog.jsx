export default function EventLog({ events, engine }) {
    const cooldowns = engine?.services_in_cooldown || []

    return (
        <div>
            <div className="grid-3" style={{ marginBottom: 16 }}>
                <div className="card">
                    <div className="metric-lbl">Policies Active</div>
                    <div className="metric-val" style={{ color: 'var(--accent)' }}>
                        {engine?.policies_loaded ?? 0}
                    </div>
                </div>
                <div className="card">
                    <div className="metric-lbl">Total Recoveries</div>
                    <div className="metric-val" style={{ color: 'var(--ok)' }}>
                        {engine?.total_recoveries ?? 0}
                    </div>
                </div>
                <div className="card">
                    <div className="metric-lbl">In Cooldown</div>
                    <div className="metric-val" style={{ color: 'var(--warn)' }}>
                        {cooldowns.length}
                    </div>
                </div>
            </div>

            {cooldowns.length > 0 && (
                <div className="card" style={{ marginBottom: 16 }}>
                    <div className="card-title" style={{ marginBottom: 10 }}>Cooldown</div>
                    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                        {cooldowns.map(svc => (
                            <span key={svc} className="tag medium">{svc}</span>
                        ))}
                    </div>
                </div>
            )}

            <div className="card">
                <div className="card-header">
                    <div className="card-title">Recovery Events</div>
                    <div className="card-subtitle">{events.length} events &middot; live via WebSocket</div>
                </div>

                {events.length === 0 ? (
                    <div className="placeholder">
                        No recovery events yet. Events stream here when the decision engine acts.
                    </div>
                ) : (
                    <div className="event-list">
                        {events.map((evt, i) => (
                            <div key={evt.id || i} className="event-row">
                                <div className={`evt-dot ${evt.status}`} />
                                <span className="evt-svc">{evt.service}</span>
                                <span className="evt-act">{evt.action}</span>
                                <span className={`tag ${evt.risk_level}`}>{evt.risk_level}</span>
                                <span style={{ fontSize: 11, color: 'var(--text-2)' }}>
                                    {evt.policy_matched}
                                </span>
                                {evt.duration_seconds != null && (
                                    <span style={{ fontSize: 11, color: 'var(--teal)', fontFamily: "'JetBrains Mono', monospace" }}>
                                        {evt.duration_seconds}s
                                    </span>
                                )}
                                {evt.error && (
                                    <span style={{ fontSize: 10, color: 'var(--err)' }} title={evt.error}>
                                        {evt.error.slice(0, 40)}
                                    </span>
                                )}
                                <span className="evt-time">
                                    {new Date(evt.timestamp).toLocaleTimeString('en-GB', { hour12: false })}
                                </span>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    )
}
