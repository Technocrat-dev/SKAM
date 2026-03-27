import { useMemo } from 'react'

const SERVICE_CONNECTIONS = [
    { from: 'api-gateway', to: 'user-service' },
    { from: 'api-gateway', to: 'product-service' },
    { from: 'api-gateway', to: 'order-service' },
    { from: 'api-gateway', to: 'cart-service' },
    { from: 'order-service', to: 'payment-service' },
    { from: 'order-service', to: 'notification-service' },
    { from: 'payment-service', to: 'notification-service' },
]

function getScoreClass(score) {
    if (score > 0.7) return 'danger'
    if (score > 0.4) return 'warning'
    return 'safe'
}

function getNodeStatus(score, isAnomaly) {
    if (isAnomaly) return 'anomaly'
    if (score > 0.4) return 'warning'
    return ''
}

export default function ServiceTopology({ scores }) {
    const scoreMap = useMemo(() => {
        const map = {}
        scores.forEach(s => { map[s.service] = s })
        return map
    }, [scores])

    const services = [
        'api-gateway', 'user-service', 'product-service',
        'order-service', 'cart-service', 'payment-service', 'notification-service',
    ]

    return (
        <div>
            <div className="card" style={{ marginBottom: 20 }}>
                <div className="card-header">
                    <div className="card-title">🗺️ Service Topology</div>
                    <div className="card-subtitle">{scores.length} services monitored</div>
                </div>

                {/* SVG Connection Map */}
                <svg viewBox="0 0 800 300" style={{ width: '100%', height: 300, marginBottom: 20 }}>
                    {/* Connections */}
                    {SERVICE_CONNECTIONS.map((conn, i) => {
                        const fromPos = getPosition(conn.from)
                        const toPos = getPosition(conn.to)
                        const fromAnomaly = scoreMap[conn.from]?.is_anomaly
                        const toAnomaly = scoreMap[conn.to]?.is_anomaly
                        return (
                            <line
                                key={i}
                                x1={fromPos.x} y1={fromPos.y}
                                x2={toPos.x} y2={toPos.y}
                                stroke={fromAnomaly || toAnomaly ? '#ef4444' : '#2a3654'}
                                strokeWidth={fromAnomaly || toAnomaly ? 2 : 1}
                                strokeDasharray={fromAnomaly || toAnomaly ? '4 4' : 'none'}
                                opacity={0.6}
                            />
                        )
                    })}

                    {/* Nodes */}
                    {services.map(svc => {
                        const pos = getPosition(svc)
                        const data = scoreMap[svc]
                        const score = data?.ensemble_score || 0
                        const isAnomaly = data?.is_anomaly || false
                        const color = isAnomaly ? '#ef4444' : score > 0.4 ? '#eab308' : '#22c55e'

                        return (
                            <g key={svc}>
                                {/* Glow */}
                                {isAnomaly && (
                                    <circle cx={pos.x} cy={pos.y} r={32} fill={color} opacity={0.1}>
                                        <animate attributeName="r" values="32;40;32" dur="2s" repeatCount="indefinite" />
                                        <animate attributeName="opacity" values="0.1;0.2;0.1" dur="2s" repeatCount="indefinite" />
                                    </circle>
                                )}
                                <circle cx={pos.x} cy={pos.y} r={24} fill="#1a2235" stroke={color} strokeWidth={2} />
                                <text x={pos.x} y={pos.y - 2} textAnchor="middle" fill={color} fontSize={10} fontWeight={600}>
                                    {score.toFixed(2)}
                                </text>
                                <text x={pos.x} y={pos.y + 38} textAnchor="middle" fill="#8b95a8" fontSize={10}>
                                    {svc.replace('-service', '').replace('-', ' ')}
                                </text>
                            </g>
                        )
                    })}
                </svg>
            </div>

            {/* Service Cards Grid */}
            <div className="topology-grid">
                {services.map(svc => {
                    const data = scoreMap[svc]
                    const score = data?.ensemble_score || 0
                    const isAnomaly = data?.is_anomaly || false
                    return (
                        <div key={svc} className={`service-node ${getNodeStatus(score, isAnomaly)}`}>
                            <div className="service-name">{svc}</div>
                            <div className={`service-score score-${getScoreClass(score)}`}>
                                {score.toFixed(3)}
                            </div>
                            <div className="service-label">Anomaly Score</div>
                            {data?.features && (
                                <div style={{ marginTop: 12, fontSize: 11, color: '#5a647a', textAlign: 'left' }}>
                                    <div>RPS: {(data.features.request_rate || 0).toFixed(1)}</div>
                                    <div>Err: {((data.features.error_ratio || 0) * 100).toFixed(1)}%</div>
                                    <div>P99: {((data.features.latency_p99 || 0) * 1000).toFixed(0)}ms</div>
                                </div>
                            )}
                        </div>
                    )
                })}
            </div>
        </div>
    )
}

function getPosition(service) {
    const positions = {
        'api-gateway': { x: 400, y: 40 },
        'user-service': { x: 140, y: 140 },
        'product-service': { x: 300, y: 140 },
        'order-service': { x: 500, y: 140 },
        'cart-service': { x: 660, y: 140 },
        'payment-service': { x: 350, y: 240 },
        'notification-service': { x: 550, y: 240 },
    }
    return positions[service] || { x: 400, y: 150 }
}
