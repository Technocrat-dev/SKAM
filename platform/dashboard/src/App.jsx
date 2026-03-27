import { useState, useEffect, useRef } from 'react'
import './App.css'
import ServiceTopology from './components/ServiceTopology'
import AnomalyTimeline from './components/AnomalyTimeline'
import ChaosPanel from './components/ChaosPanel'
import LiveMetrics from './components/LiveMetrics'
import EventLog from './components/EventLog'

const API_BASE = import.meta.env.VITE_API_BASE || ''

function App() {
  const [scores, setScores] = useState([])
  const [events, setEvents] = useState([])
  const [detectorStatus, setDetectorStatus] = useState(null)
  const [engineStatus, setEngineStatus] = useState(null)
  const [activeTab, setActiveTab] = useState('topology')
  const wsRef = useRef(null)

  // Poll anomaly scores
  useEffect(() => {
    const fetchScores = async () => {
      try {
        const res = await fetch(`${API_BASE}/anomaly/api/scores`)
        const data = await res.json()
        setScores(data.scores || [])
      } catch (e) { console.debug('Scores fetch failed:', e) }
    }
    fetchScores()
    const id = setInterval(fetchScores, 5000)
    return () => clearInterval(id)
  }, [])

  // Poll statuses
  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const [det, eng] = await Promise.all([
          fetch(`${API_BASE}/anomaly/api/status`).then(r => r.json()),
          fetch(`${API_BASE}/decision/api/status`).then(r => r.json()),
        ])
        setDetectorStatus(det)
        setEngineStatus(eng)
      } catch (e) { console.debug('Status fetch failed:', e) }
    }
    fetchStatus()
    const id = setInterval(fetchStatus, 10000)
    return () => clearInterval(id)
  }, [])

  // WebSocket for real-time events
  useEffect(() => {
    const wsUrl = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/decision/ws/events`
    const connect = () => {
      const ws = new WebSocket(wsUrl)
      ws.onmessage = (e) => {
        const event = JSON.parse(e.data)
        setEvents(prev => [event, ...prev].slice(0, 200))
      }
      ws.onclose = () => setTimeout(connect, 3000)
      wsRef.current = ws
    }
    connect()
    return () => wsRef.current?.close()
  }, [])

  const anomalyCount = scores.filter(s => s.is_anomaly).length
  const healthyCount = scores.length - anomalyCount

  return (
    <div className="app">
      <header className="header">
        <div className="header-left">
          <h1 className="logo">
            <span className="logo-icon">🛡️</span>
            SKAM
          </h1>
          <span className="subtitle">Self-healing Kubernetes Autonomous Monitor</span>
        </div>
        <div className="header-stats">
          <div className="stat-pill healthy">
            <span className="stat-dot" />
            {healthyCount} Healthy
          </div>
          <div className="stat-pill anomaly">
            <span className="stat-dot" />
            {anomalyCount} Anomalies
          </div>
          <div className="stat-pill recovery">
            <span className="stat-dot" />
            {engineStatus?.total_recoveries || 0} Recoveries
          </div>
        </div>
      </header>

      <nav className="tab-bar">
        {[
          { id: 'topology', label: '🗺️ Topology', },
          { id: 'anomaly', label: '📊 Anomaly Timeline' },
          { id: 'chaos', label: '💥 Chaos Control' },
          { id: 'metrics', label: '📈 Live Metrics' },
          { id: 'events', label: '📋 Event Log' },
        ].map(tab => (
          <button
            key={tab.id}
            className={`tab ${activeTab === tab.id ? 'active' : ''}`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      <main className="content">
        {activeTab === 'topology' && <ServiceTopology scores={scores} />}
        {activeTab === 'anomaly' && <AnomalyTimeline scores={scores} />}
        {activeTab === 'chaos' && <ChaosPanel apiBase={API_BASE} />}
        {activeTab === 'metrics' && <LiveMetrics scores={scores} detectorStatus={detectorStatus} />}
        {activeTab === 'events' && <EventLog events={events} engineStatus={engineStatus} />}
      </main>
    </div>
  )
}

export default App
