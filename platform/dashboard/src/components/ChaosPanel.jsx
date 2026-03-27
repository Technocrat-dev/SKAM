import { useState } from 'react'

const FAULT_TYPES = [
    { id: 'pod_kill', icon: '💀', name: 'Pod Kill', desc: 'Kill random pods' },
    { id: 'pod_crashloop', icon: '🔄', name: 'Crashloop', desc: 'Force image pull backoff' },
    { id: 'cpu_stress', icon: '🔥', name: 'CPU Stress', desc: 'Saturate CPU cores' },
    { id: 'memory_pressure', icon: '💣', name: 'Memory Pressure', desc: 'OOMKill trigger' },
    { id: 'network_partition', icon: '🔒', name: 'Net Partition', desc: 'Block ingress traffic' },
    { id: 'latency_injection', icon: '🐌', name: 'Latency', desc: 'Inject network delay' },
]

const SERVICES = [
    'api-gateway', 'user-service', 'product-service',
    'order-service', 'cart-service', 'payment-service', 'notification-service',
]

export default function ChaosPanel({ apiBase }) {
    const [targetService, setTargetService] = useState('user-service')
    const [duration, setDuration] = useState(30)
    const [experiments, setExperiments] = useState([])
    const [running, setRunning] = useState(false)

    const injectChaos = async (faultType) => {
        setRunning(true)
        try {
            const res = await fetch(`${apiBase}/chaos/api/experiments`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    fault_type: faultType,
                    target: {
                        namespace: 'default',
                        label_selector: `app=${targetService}`,
                    },
                    duration_seconds: duration,
                    parameters: {},
                }),
            })
            const data = await res.json()
            setExperiments(prev => [data, ...prev])
        } catch (e) {
            console.error('Chaos injection failed:', e)
        } finally {
            setRunning(false)
        }
    }

    return (
        <div>
            {/* Controls */}
            <div className="card" style={{ marginBottom: 20 }}>
                <div className="card-header">
                    <div className="card-title">💥 Chaos Control Panel</div>
                    <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                        <select className="select" value={targetService} onChange={e => setTargetService(e.target.value)}>
                            {SERVICES.map(s => <option key={s} value={s}>{s}</option>)}
                        </select>
                        <select className="select" value={duration} onChange={e => setDuration(Number(e.target.value))}>
                            <option value={15}>15s</option>
                            <option value={30}>30s</option>
                            <option value={60}>60s</option>
                            <option value={120}>120s</option>
                        </select>
                    </div>
                </div>

                <div className="chaos-grid">
                    {FAULT_TYPES.map(fault => (
                        <button
                            key={fault.id}
                            className="chaos-btn"
                            onClick={() => injectChaos(fault.id)}
                            disabled={running}
                        >
                            <span className="icon">{fault.icon}</span>
                            <span>{fault.name}</span>
                            <span className="label">{fault.desc}</span>
                        </button>
                    ))}
                </div>
            </div>

            {/* Experiment History */}
            <div className="card">
                <div className="card-header">
                    <div className="card-title">🧪 Experiment History</div>
                    <div className="card-subtitle">{experiments.length} experiments</div>
                </div>

                {experiments.length === 0 ? (
                    <div className="empty-state">
                        <div className="icon">🧪</div>
                        <p>No experiments yet. Inject chaos above to start.</p>
                    </div>
                ) : (
                    <div className="event-list">
                        {experiments.map((exp, i) => (
                            <div key={i} className="event-item">
                                <div className={`event-status ${exp.status || 'pending'}`} />
                                <span className="event-service">
                                    {FAULT_TYPES.find(f => f.id === exp.fault_type)?.icon || '🧪'}{' '}
                                    {exp.fault_type}
                                </span>
                                <span className="event-action">{exp.target?.label_selector || ''}</span>
                                <span>
                                    <span className={`badge ${exp.status === 'completed' ? 'low' : exp.status === 'running' ? 'medium' : 'high'}`}>
                                        {exp.status || 'unknown'}
                                    </span>
                                </span>
                                <span className="event-time">{exp.duration_seconds || duration}s</span>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    )
}
