export default function EventLog({ events, engineStatus }) {
    return (
        <div>
            {/* Engine Status */}
            <div className="grid-3" style={{ marginBottom: 20 }}>
                <div className="card">
                    <div className="metric-label">Policies Loaded</div>
                    <div className="metric-value" style={{ color: 'var(--accent)' }}>
                        {engineStatus?.policies_loaded || 0}
                    </div>
                </div>
                <div className="card">
                    <div className="metric-label">Total Recoveries</div>
                    <div className="metric-value" style={{ color: 'var(--green)' }}>
                        {engineStatus?.total_recoveries || 0}
                    </div>
                </div>
                <div className="card">
                    <div className="metric-label">Cooldowns Active</div>
                    <div className="metric-value" style={{ color: 'var(--yellow)' }}>
                        {engineStatus?.services_in_cooldown?.length || 0}
                    </div>
                </div>
            </div>

            {/* Cooldown List */}
            {engineStatus?.services_in_cooldown?.length > 0 && (
                <div className="card" style={{ marginBottom: 20 }}>
                    <div className="card-title" style={{ marginBottom: 12 }}>⏳ Services in Cooldown</div>
                    <div style={{ display: 'flex', gap: 8 }}>
                        {engineStatus.services_in_cooldown.map(svc => (
                            <span key={svc} className="badge medium">{svc}</span>
                        ))}
                    </div>
                </div>
            )}

            {/* Event Stream */}
            <div className="card">
                <div className="card-header">
                    <div className="card-title">📋 Recovery Event Stream</div>
                    <div className="card-subtitle">{events.length} events (real-time via WebSocket)</div>
                </div>

                {events.length === 0 ? (
                    <div className="empty-state">
                        <div className="icon">📋</div>
                        <p>No recovery events yet. Events will appear here in real-time when the decision engine triggers healing actions.</p>
                    </div>
                ) : (
                    <div className="event-list">
                        {events.map((evt, i) => (
                            <div key={evt.id || i} className="event-item">
                                <div className={`event-status ${evt.status}`} />
                                <span className="event-service">{evt.service}</span>
                                <span className="event-action">{evt.action}</span>
                                <span className={`badge ${evt.risk_level}`}>{evt.risk_level}</span>
                                <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                                    {evt.policy_matched}
                                </span>
                                {evt.duration_seconds && (
                                    <span style={{ fontSize: 12, color: 'var(--cyan)', fontFamily: "'JetBrains Mono', monospace" }}>
                                        {evt.duration_seconds}s
                                    </span>
                                )}
                                {evt.error && (
                                    <span style={{ fontSize: 11, color: 'var(--red)' }} title={evt.error}>
                                        ⚠️ {evt.error.slice(0, 40)}
                                    </span>
                                )}
                                <span className="event-time">
                                    {new Date(evt.timestamp).toLocaleTimeString()}
                                </span>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    )
}
