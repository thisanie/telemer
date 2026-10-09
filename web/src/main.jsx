import { useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'

const SOCKET_URL = import.meta.env.VITE_SOCKET_URL || 'ws://127.0.0.1:8001/ws/call'

function App() {
  const socketRef = useRef(null)
  const recognitionRef = useRef(null)
  const sentTranscriptRef = useRef(false)
  const latestInterimRef = useRef('')
  const [connection, setConnection] = useState('connecting')
  const [question, setQuestion] = useState(null)
  const [interim, setInterim] = useState('')
  const [transcript, setTranscript] = useState('')
  const [turns, setTurns] = useState([])
  const [listening, setListening] = useState(false)
  const [status, setStatus] = useState('Ready to begin')
  const [ended, setEnded] = useState(false)
  const [manualText, setManualText] = useState('')
  const [showFallback, setShowFallback] = useState(false)

  useEffect(() => {
    const socket = new WebSocket(SOCKET_URL)
    socketRef.current = socket
    socket.onopen = () => setConnection('online')
    socket.onclose = () => setConnection('offline')
    socket.onerror = () => setConnection('offline')
    socket.onmessage = (event) => {
      const message = JSON.parse(event.data)
      if (message.type === 'question') {
        setQuestion(message.question)
        setStatus('Listening for your answer')
        speak(message.question.spokenText)
      }
      if (message.type === 'answer.processed') {
        setTurns((previous) => [...previous, message])
        setTranscript('')
        setInterim('')
        setStatus(message.transition === 'clarify' ? 'Please clarify your answer' : 'Next question ready')
      }
      if (message.type === 'call.ended') {
        setEnded(true)
        setListening(false)
        setStatus(message.status === 'complete' ? 'Call complete' : 'Call transferred')
      }
    }
    return () => socket.close()
  }, [])

  function speak(text) {
    if ('speechSynthesis' in window) {
      window.speechSynthesis.cancel()
      const utterance = new SpeechSynthesisUtterance(text)
      utterance.lang = 'hi-IN'
      utterance.rate = 0.95
      window.speechSynthesis.speak(utterance)
    }
  }

  function startListening() {
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!Recognition) {
      setShowFallback(true)
      setStatus('Use Chrome or Edge for live browser transcription')
      return
    }
    const recognition = new Recognition()
    recognition.lang = 'hi-IN'
    recognition.continuous = false
    recognition.interimResults = true
    sentTranscriptRef.current = false
    latestInterimRef.current = ''
    recognition.onstart = () => { setListening(true); setStatus('Listening...') }
    recognition.onresult = (event) => {
      let interimText = ''
      let finalText = ''
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const text = event.results[index][0].transcript
        if (event.results[index].isFinal) finalText += text
        else interimText += text
      }
      setInterim(interimText)
      latestInterimRef.current = interimText
      if (finalText) {
        sendTranscript(finalText.trim())
      }
    }
    recognition.onerror = (event) => {
      setListening(false)
      setShowFallback(true)
      setStatus(`Microphone error: ${event.error}. Use the fallback below.`)
    }
    recognition.onend = () => {
      setListening(false)
      if (!sentTranscriptRef.current) sendTranscript(latestInterimRef.current.trim())
    }
    recognitionRef.current = recognition
    recognition.start()
  }

  function sendTranscript(text) {
    if (!text || sentTranscriptRef.current || socketRef.current?.readyState !== WebSocket.OPEN) return
    sentTranscriptRef.current = true
    setTranscript(text)
    setInterim('')
    setStatus('Processing response...')
    socketRef.current.send(JSON.stringify({ type: 'transcript.final', text }))
  }

  function stopListening() {
    recognitionRef.current?.stop()
    setListening(false)
    setStatus('Paused')
  }

  function resetCall() {
    setTurns([])
    setTranscript('')
    setInterim('')
    setEnded(false)
    setManualText('')
    setShowFallback(false)
    setStatus('Starting a new call')
    socketRef.current?.send(JSON.stringify({ type: 'reset' }))
  }

  function submitManualText(event) {
    event.preventDefault()
    sendTranscript(manualText.trim())
    setManualText('')
  }

  const extractedData = new Map()
  turns.forEach((turn, index) => {
    const fields = Array.isArray(turn.analysis?.extracted_data)
      ? turn.analysis.extracted_data
      : []
    if (fields.length > 0) {
      fields.forEach(({ key, value }) => {
        if (key != null && value != null) {
          extractedData.set(String(key), String(value))
        }
      })
    } else if (turn.analysis?.normalized_answer) {
      extractedData.set(
        turn.questionId || `answer_${index + 1}`,
        String(turn.analysis.normalized_answer),
      )
    }
  })

  return (
    <main className="shell">
      <header className="topbar">
        <div className="brand"><span className="brand-mark">t</span><span>teleMER</span></div>
        <div className={`connection ${connection}`}><span className="dot" />{connection}</div>
      </header>
      <section className="hero">
        <div className="eyebrow">LIVE INTAKE / 001</div>
        <h1>A quieter way to<br /><em>get covered.</em></h1>
        <p className="lede">A voice-led insurance intake. Speak naturally. We will guide the next step.</p>
      </section>
      <section className="call-grid">
        <div className="call-panel">
          <div className="panel-head"><span>TELEMER ASSISTANT</span><span className="wave-label">{status}</span></div>
          <div className="question-area">
            <div className="pulse-ring"><div className="mic-symbol">◉</div></div>
            <div className="question-copy">
              <span className="question-tag">CURRENT QUESTION</span>
              <h2>{question?.text || 'Connecting to your call...'}</h2>
              <p>{interim || transcript || 'Your words will appear here as you speak.'}</p>
            </div>
          </div>
          <div className="controls">
            <button className={`talk-button ${listening ? 'active' : ''}`} onClick={listening ? stopListening : startListening} disabled={ended || connection !== 'online'}>
              <span className="button-icon">{listening ? '■' : '●'}</span>{listening ? 'Stop listening' : 'Start speaking'}
            </button>
            <button className="reset-button" onClick={resetCall}>Reset call</button>
          </div>
          {showFallback && <form className="fallback-form" onSubmit={submitManualText}>
            <input value={manualText} onChange={(event) => setManualText(event.target.value)} placeholder="Browser speech is unavailable. Type a test response..." aria-label="Fallback response" />
            <button type="submit" disabled={!manualText.trim()}>Send</button>
          </form>}
          <div className="privacy-note"><span>⌁</span> No audio is stored in this browser demo</div>
        </div>
        <aside className="timeline">
          <div className="panel-head"><span>CALL THREAD</span><span>{turns.length.toString().padStart(2, '0')} TURNS</span></div>
          {turns.length === 0 ? <div className="empty-thread">Your live transcript<br />will settle here.</div> : turns.map((turn, index) => (
            <div className="turn" key={`${turn.transcript}-${index}`}><span className="turn-number">0{index + 1}</span><div><small>YOU SAID</small><p>{turn.transcript}</p></div></div>
          ))}
          <section className="extracted-data">
            <div className="panel-head"><span>EXTRACTED DATA</span><span>{extractedData.size} FIELDS</span></div>
            {extractedData.size === 0
              ? <p className="extracted-empty">Answers will appear here after they are processed.</p>
              : Array.from(extractedData, ([key, value]) => (
                <div className="extracted-field" key={key}>
                  <small>{String(key).replaceAll('_', ' ')}</small>
                  <p>{value}</p>
                </div>
              ))}
          </section>
        </aside>
      </section>
    </main>
  )
}

const root = window.__telemerRoot || createRoot(document.getElementById('root'))
window.__telemerRoot = root
root.render(<App />)
