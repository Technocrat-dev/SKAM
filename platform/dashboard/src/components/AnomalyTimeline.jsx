import { useState, useEffect, useRef } from 'react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, Area, AreaChart, ReferenceLine } from 'recharts'

const COLORS = {
    'api-gateway': '#6366f1',
    'user-service': '#06b6d4',
    'product-service': '#22c55e',
    'order-service': '#eab308',
    'cart-service': '#a855f7',
    'payment-service': '#ef4444',
    'notification-service': '#f97316',
}

export default function AnomalyTimeline({ scores }) {
    const [history, setHistory] = useState([])
    const [selectedService, setSelectedService] = useState('all')
    const maxPoints = 60

    // Append new data points
    useEffect(() => {
        if (!scores.length) return
        const point = { time: new Date().toLocaleTimeString() }
        scores.forEach(s => {
            point[s.service] = s.ensemble_score
        })
        setHistory(prev => [...prev.slice(-(maxPoints - 1)), point])
    }, [scores])

    const services = scores.map(s => s.service)
    const filtered = selectedService === 'all' ? services : [selectedService]

    return (
        <div>
            <div className="card">
                <div className="card-header">
                    <div className="card-title">📊 Anomaly Score Timeline</div>
                    <select
                        className="select"
                        value={selectedService}
                        onChange={e => setSelectedService(e.target.value)}
                    >
                        <option value="all">All Services</option>
                        {services.map(s => (
                            <option key={s} value={s}>{s}</option>
                        ))}
                    </select>
                </div>

                {history.length < 2 ? (
                    <div className="empty-state">
                        <div className="icon">📈</div>
                        <p>Collecting data... Timeline will appear shortly.</p>
                    </div>
                ) : (
                    <ResponsiveContainer width="100%" height={400}>
                        <AreaChart data={history}>
                            <defs>
                                {filtered.map(svc => (
                                    <linearGradient key={svc} id={`grad-${svc}`} x1="0" y1="0" x2="0" y2="1">
                                        <stop offset="5%" stopColor={COLORS[svc] || '#6366f1'} stopOpacity={0.3} />
                                        <stop offset="95%" stopColor={COLORS[svc] || '#6366f1'} stopOpacity={0} />
                                    </linearGradient>
                                ))}
                            </defs>
                            <CartesianGrid strokeDasharray="3 3" stroke="#2a3654" />
                            <XAxis dataKey="time" stroke="#5a647a" fontSize={11} />
                            <YAxis domain={[0, 1]} stroke="#5a647a" fontSize={11} />
                            <Tooltip
                                contentStyle={{
                                    background: '#1a2235',
                                    border: '1px solid #2a3654',
                                    borderRadius: 8,
                                    fontSize: 12,
                                }}
                            />
                            <ReferenceLine y={0.7} stroke="#ef4444" strokeDasharray="3 3" label={{ value: 'Threshold', fill: '#ef4444', fontSize: 11 }} />
                            {filtered.map(svc => (
                                <Area
                                    key={svc}
                                    type="monotone"
                                    dataKey={svc}
                                    stroke={COLORS[svc] || '#6366f1'}
                                    fill={`url(#grad-${svc})`}
                                    strokeWidth={2}
                                    dot={false}
                                    isAnimationActive={false}
                                />
                            ))}
                        </AreaChart>
                    </ResponsiveContainer>
                )}
            </div>

            {/* Per-Service Score Breakdown */}
            <div className="grid-3" style={{ marginTop: 20 }}>
                {scores.map(s => (
                    <div key={s.service} className="card">
                        <div className="card-title" style={{ fontSize: 13, marginBottom: 12 }}>
                            <span style={{ color: COLORS[s.service], fontSize: 10 }}>●</span>
                            {s.service}
                        </div>
                        <div className="grid-3" style={{ gap: 8 }}>
                            <div>
                                <div className="metric-value" style={{ fontSize: 18, color: '#6366f1' }}>
                                    {s.isoforest_score?.toFixed(3)}
                                </div>
                                <div className="metric-label" style={{ fontSize: 10 }}>IsoForest</div>
                            </div>
                            <div>
                                <div className="metric-value" style={{ fontSize: 18, color: '#06b6d4' }}>
                                    {s.lstm_score?.toFixed(3)}
                                </div>
                                <div className="metric-label" style={{ fontSize: 10 }}>LSTM</div>
                            </div>
                            <div>
                                <div className="metric-value" style={{ fontSize: 18, color: s.is_anomaly ? '#ef4444' : '#22c55e' }}>
                                    {s.ensemble_score?.toFixed(3)}
                                </div>
                                <div className="metric-label" style={{ fontSize: 10 }}>Ensemble</div>
                            </div>
                        </div>
                    </div>
                ))}
            </div>
        </div>
    )
}
