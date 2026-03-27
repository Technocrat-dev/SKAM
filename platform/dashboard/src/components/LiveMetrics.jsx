import { useMemo } from 'react'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis } from 'recharts'

export default function LiveMetrics({ scores, detectorStatus }) {
    const radarData = useMemo(() => {
        return scores.map(s => ({
            service: s.service.replace('-service', '').replace('api-', 'gw'),
            'Error Ratio': Math.min((s.features?.error_ratio || 0) * 100, 100),
            'Latency (ms)': Math.min((s.features?.latency_p99 || 0) * 1000, 500) / 5,
            'CPU Z-Score': Math.min(Math.abs(s.features?.cpu_zscore || 0) * 20, 100),
            'Anomaly': (s.ensemble_score || 0) * 100,
        }))
    }, [scores])

    const barData = useMemo(() => {
        return scores.map(s => ({
            name: s.service.replace('-service', '').replace('api-', 'gw'),
            isoforest: s.isoforest_score || 0,
            lstm: s.lstm_score || 0,
            ensemble: s.ensemble_score || 0,
        }))
    }, [scores])

    return (
        <div>
            {/* Status Overview */}
            <div className="grid-3" style={{ marginBottom: 20 }}>
                <div className="card">
                    <div className="metric-label">Detection Interval</div>
                    <div className="metric-value" style={{ color: 'var(--accent)' }}>15s</div>
                </div>
                <div className="card">
                    <div className="metric-label">Services Monitored</div>
                    <div className="metric-value" style={{ color: 'var(--cyan)' }}>
                        {detectorStatus?.services_monitored || scores.length}
                    </div>
                </div>
                <div className="card">
                    <div className="metric-label">Total Anomalies</div>
                    <div className="metric-value" style={{ color: 'var(--red)' }}>
                        {detectorStatus?.total_anomalies || 0}
                    </div>
                </div>
            </div>

            {/* Charts */}
            <div className="grid-2">
                {/* Model Score Comparison */}
                <div className="card">
                    <div className="card-title" style={{ marginBottom: 16 }}>🤖 Model Score Comparison</div>
                    {barData.length > 0 ? (
                        <ResponsiveContainer width="100%" height={300}>
                            <BarChart data={barData}>
                                <CartesianGrid strokeDasharray="3 3" stroke="#2a3654" />
                                <XAxis dataKey="name" stroke="#5a647a" fontSize={11} />
                                <YAxis domain={[0, 1]} stroke="#5a647a" fontSize={11} />
                                <Tooltip
                                    contentStyle={{
                                        background: '#1a2235',
                                        border: '1px solid #2a3654',
                                        borderRadius: 8,
                                        fontSize: 12,
                                    }}
                                />
                                <Bar dataKey="isoforest" fill="#6366f1" name="Isolation Forest" radius={[4, 4, 0, 0]} />
                                <Bar dataKey="lstm" fill="#06b6d4" name="LSTM Autoencoder" radius={[4, 4, 0, 0]} />
                                <Bar dataKey="ensemble" fill="#a855f7" name="Ensemble" radius={[4, 4, 0, 0]} />
                            </BarChart>
                        </ResponsiveContainer>
                    ) : (
                        <div className="empty-state"><p>Waiting for data...</p></div>
                    )}
                </div>

                {/* Feature Radar */}
                <div className="card">
                    <div className="card-title" style={{ marginBottom: 16 }}>🎯 Feature Radar</div>
                    {radarData.length > 0 ? (
                        <ResponsiveContainer width="100%" height={300}>
                            <RadarChart data={radarData}>
                                <PolarGrid stroke="#2a3654" />
                                <PolarAngleAxis dataKey="service" stroke="#5a647a" fontSize={11} />
                                <PolarRadiusAxis domain={[0, 100]} stroke="#5a647a" fontSize={9} />
                                <Radar name="Error Ratio" dataKey="Error Ratio" stroke="#ef4444" fill="#ef4444" fillOpacity={0.15} />
                                <Radar name="Anomaly" dataKey="Anomaly" stroke="#a855f7" fill="#a855f7" fillOpacity={0.15} />
                                <Tooltip
                                    contentStyle={{
                                        background: '#1a2235',
                                        border: '1px solid #2a3654',
                                        borderRadius: 8,
                                        fontSize: 12,
                                    }}
                                />
                            </RadarChart>
                        </ResponsiveContainer>
                    ) : (
                        <div className="empty-state"><p>Waiting for data...</p></div>
                    )}
                </div>
            </div>

            {/* Feature Detail Table */}
            <div className="card" style={{ marginTop: 20 }}>
                <div className="card-title" style={{ marginBottom: 16 }}>📋 Feature Breakdown</div>
                <div style={{ overflowX: 'auto' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                        <thead>
                            <tr style={{ borderBottom: '1px solid var(--border)' }}>
                                <th style={thStyle}>Service</th>
                                <th style={thStyle}>RPS</th>
                                <th style={thStyle}>Error%</th>
                                <th style={thStyle}>P50 (ms)</th>
                                <th style={thStyle}>P99 (ms)</th>
                                <th style={thStyle}>CPU</th>
                                <th style={thStyle}>Mem (MB)</th>
                                <th style={thStyle}>Restarts</th>
                            </tr>
                        </thead>
                        <tbody>
                            {scores.map(s => (
                                <tr key={s.service} style={{ borderBottom: '1px solid var(--border)' }}>
                                    <td style={{ ...tdStyle, fontWeight: 600 }}>{s.service}</td>
                                    <td style={tdStyle}>{(s.features?.request_rate || 0).toFixed(1)}</td>
                                    <td style={tdStyle}>{((s.features?.error_ratio || 0) * 100).toFixed(1)}%</td>
                                    <td style={tdStyle}>{((s.features?.latency_p50 || 0) * 1000).toFixed(0)}</td>
                                    <td style={tdStyle}>{((s.features?.latency_p99 || 0) * 1000).toFixed(0)}</td>
                                    <td style={tdStyle}>{(s.features?.cpu_usage || 0).toFixed(3)}</td>
                                    <td style={tdStyle}>{(s.features?.memory_usage_mb || 0).toFixed(1)}</td>
                                    <td style={tdStyle}>{s.features?.restart_count || 0}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    )
}

const thStyle = {
    padding: '10px 12px',
    textAlign: 'left',
    color: 'var(--text-muted)',
    fontWeight: 500,
    fontSize: 11,
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
}

const tdStyle = {
    padding: '10px 12px',
    color: 'var(--text-secondary)',
    fontFamily: "'JetBrains Mono', monospace",
    fontSize: 12,
}
