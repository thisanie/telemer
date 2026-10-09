import { useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'

const SOCKET_URL = import.meta.env.VITE_SOCKET_URL || 'ws://127.0.0.1:8001/ws/call'

function App() {
  const socketRef = useRef(null)
  const recognitionRef = useRef(null)
  const sentTranscriptRef = useRef(false)
  const latestInterimRef = useRef('')
  const recognitionErrorRef = useRef(false)
  const transcriptPendingRef = useRef(false)
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
    let mounted = true
    const socket = new WebSocket(SOCKET_URL)
    socketRef.current = socket
    socket.onopen = () => setConnection('online')
    socket.onclose = () => {
      if (!mounted) return
      setConnection('offline')
      void stopListening()
    }
    socket.onerror = () => setConnection('offline')
    socket.onmessage = (event) => {
      const message = JSON.parse(event.data)
      if (message.type === 'question') {
        sentTranscriptRef.current = false
        latestInterimRef.current = ''
        transcriptPendingRef.current = false
        setQuestion(message.question)
        setStatus('Listening for your answer')
        speak(message.question.spokenText)
      }
      if (message.type === 'answer.processed') {
        transcriptPendingRef.current = false
        setTurns((previous) => [...previous, message])
        setTranscript('')
        setInterim('')
        setStatus(message.transition === 'clarify' ? 'Please clarify your answer' : 'Next question ready')
      }
      if (message.type === 'call.ended') {
        setEnded(true)
        recognitionRef.current?.stop()
        setListening(false)
        setStatus(message.status === 'complete' ? 'Call complete' : 'Call transferred')
      }
    }
    return () => {
      mounted = false
      recognitionRef.current?.stop()
      socket.close()
    }
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
    if (listening || transcriptPendingRef.current || ended) return

    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!Recognition) {
      setShowFallback(true)
      setStatus('Speech recognition is not supported in this browser. Type your response instead.')
      return
    }

    const recognition = new Recognition()
    recognition.lang = 'hi-IN'
    recognition.continuous = false
    recognition.interimResults = true
    sentTranscriptRef.current = false
    latestInterimRef.current = ''
    recognitionErrorRef.current = false
    setInterim('')
    setTranscript('')
    setShowFallback(false)
    setListening(true)
    setStatus('Listening...')
    recognition.onresult = (event) => {
      let finalText = ''
      let interimText = ''
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index]
        if (result.isFinal) finalText += result[0].transcript
        else interimText += result[0].transcript
      }
      const text = (finalText || interimText).trim()
      latestInterimRef.current = text
      setInterim(text)
      if (finalText.trim()) sendTranscript(finalText.trim())
    }
    recognition.onerror = (event) => {
      recognitionErrorRef.current = true
      setListening(false)
      if (event.error === 'no-speech') {
        setStatus('No speech detected. Select Start speaking to try again.')
      } else {
        setShowFallback(true)
        setStatus(`Speech recognition failed (${event.error}). Type your response instead.`)
      }
    }
    recognition.onend = () => {
      if (recognitionRef.current === recognition) recognitionRef.current = null
      setListening(false)
      if (!recognitionErrorRef.current && !sentTranscriptRef.current) {
        const text = latestInterimRef.current.trim()
        if (text) sendTranscript(text)
        else setStatus('No speech detected. Select Start speaking to try again.')
      }
    }
    recognitionRef.current = recognition
    try {
      recognition.start()
    } catch (error) {
      recognitionRef.current = null
      setListening(false)
      setShowFallback(true)
      setStatus('Could not start speech recognition. Type your response instead.')
      console.error('Could not start browser speech recognition', error)
    }
  }

  function stopListening() {
    recognitionRef.current?.stop()
    setListening(false)
  }

  function sendTranscript(text) {
    if (
      !text ||
      transcriptPendingRef.current ||
      sentTranscriptRef.current ||
      socketRef.current?.readyState !== WebSocket.OPEN
    ) return
    sentTranscriptRef.current = true
    transcriptPendingRef.current = true
    setTranscript(text)
    setInterim('')
    setStatus('Processing response...')
    socketRef.current.send(JSON.stringify({ type: 'transcript.final', text }))
  }

  function resetCall() {
    recognitionRef.current?.stop()
    recognitionRef.current = null
    sentTranscriptRef.current = false
    latestInterimRef.current = ''
    recognitionErrorRef.current = false
    transcriptPendingRef.current = false
    setTurns([])
    setTranscript('')
    setInterim('')
    setEnded(false)
    setManualText('')
    setShowFallback(false)
    setListening(false)
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
              <button className={`talk-button ${listening ? 'active' : ''}`} onClick={listening ? stopListening : startListening} disabled={ended || connection !== 'online' || transcriptPendingRef.current}>
                <span className="button-icon">{listening ? '■' : '●'}</span>{listening ? 'Stop listening' : 'Start speaking'}
            </button>
            <button className="reset-button" onClick={resetCall}>Reset call</button>
          </div>
          {showFallback && <form className="fallback-form" onSubmit={submitManualText}>
            <input value={manualText} onChange={(event) => setManualText(event.target.value)} placeholder="Microphone unavailable. Type a test response..." aria-label="Fallback response" />
            <button type="submit" disabled={!manualText.trim()}>Send</button>
          </form>}
          <div className="privacy-note"><span>⌁</span> Browser speech recognition may use an online service. This app receives text only and does not save audio.</div>
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
