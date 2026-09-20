import { useState, useRef, useEffect } from 'react'
import { Send, Sparkles, BarChart2 } from 'lucide-react'
import MessageBubble from './MessageBubble'

// Generic starter questions shown on the "no report selected" screen.
const STARTER_QUESTIONS = [
  "What's our total revenue this year?",
  "Which region is performing best?",
  "Show me monthly revenue trend",
  "How are we tracking against targets?",
  "What's our top selling product?",
]

// Per-report follow-up questions shown once a specific report is loaded.
// Keyed by report id (matches ReportMeta.id from the backend).
const STARTER_QUESTIONS_BY_REPORT = {
  'rpt-001': [
    "What's our total revenue this year?",
    "Which region is performing best?",
    "Show me monthly revenue trend",
  ],
  'rpt-002': [
    "How are we tracking against targets?",
    "Which regions are below target?",
    "What was our best quarter?",
  ],
  'rpt-003': [
    "How many new customers did we acquire?",
    "What's our churn rate?",
    "Which channel drives the most acquisitions?",
  ],
  'rpt-004': [
    "What's our top selling product?",
    "Which product has the highest margin?",
    "How many units did we sell total?",
  ],
  'rpt-005': [
    "How many tickets are open?",
    "What's our average resolution time?",
    "Which priority has the most tickets?",
  ],
  'rpt-006': [
    "What's our total billing amount?",
    "Which vendor do we owe the most?",
    "How many invoices are unpaid?",
  ],
}

const DEFAULT_REPORT_QUESTIONS = [
  "What's our total revenue this year?",
  "Which region is performing best?",
  "Show me monthly revenue trend",
]

export default function ChatWindow({ activeReport }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  useEffect(() => {
    if (activeReport) {
      const questions = STARTER_QUESTIONS_BY_REPORT[activeReport.id] || DEFAULT_REPORT_QUESTIONS
      setMessages([{
        id: Date.now(),
        role: 'assistant',
        content: `📊 ${activeReport.name} loaded. I have access to the live data for this report. Ask me anything — KPIs, trends, comparisons, or anomalies.`,
        follow_up_questions: questions,
      }])
    }
  }, [activeReport?.id])

  const sendMessage = async (text) => {
    const userText = text || input.trim()
    if (!userText || loading) return
    setInput('')

    const userMsg = { id: Date.now(), role: 'user', content: userText }
    const typingMsg = { id: 'typing', role: 'assistant', typing: true }
    setMessages(prev => [...prev, userMsg, typingMsg])
    setLoading(true)

    try {
      const history = messages.filter(m => !m.typing).slice(-8).map(m => ({ role: m.role, content: m.content }))
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: userText,
          history,
          report_context: activeReport ? `${activeReport.id} - ${activeReport.name}` : null,
        }),
      })
      const data = await res.json()
      setMessages(prev => prev.filter(m => m.id !== 'typing').concat({
        id: Date.now(),
        role: 'assistant',
        content: data.answer,
        chart: data.chart,
        follow_up_questions: data.follow_up_questions,
        data_used: data.data_used,
      }))
    } catch {
      setMessages(prev => prev.filter(m => m.id !== 'typing').concat({
        id: Date.now(), role: 'assistant', content: 'Connection error. Is the backend running?'
      }))
    } finally {
      setLoading(false)
      inputRef.current?.focus()
    }
  }

  const handleKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage() }
  }

  const showWelcomeHero = !activeReport && messages.length === 0

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {activeReport && (
        <div className="px-5 py-2.5 border-b border-[#21262D] flex items-center gap-2 bg-[#161B22]">
          <div className="w-1.5 h-1.5 rounded-full bg-[#2563EB]" />
          <span className="text-xs text-[#7D8590]">Analyzing: </span>
          <span className="text-xs text-[#E6EDF3] font-medium">{activeReport.name}</span>
          <span className="text-[10px] text-[#7D8590] ml-auto font-mono">{activeReport.workspace}</span>
        </div>
      )}

      <div className="flex-1 overflow-y-auto px-5 py-5">
        {showWelcomeHero ? (
          <div className="h-full flex flex-col items-center justify-center gap-6">
            <div className="text-center">
              <div className="w-14 h-14 rounded-2xl bg-[#2563EB]/10 border border-[#2563EB]/20 flex items-center justify-center mx-auto mb-4">
                <BarChart2 size={24} className="text-[#2563EB]" />
              </div>
              <h2 className="text-lg font-semibold text-[#E6EDF3] mb-1">Select a report to start</h2>
              <p className="text-sm text-[#7D8590] max-w-xs">Choose a Power BI report from the panel, or just ask a question below.</p>
            </div>
            <div className="w-full max-w-md">
              <p className="text-[10px] font-mono text-[#7D8590] uppercase tracking-widest mb-3 flex items-center gap-1">
                <Sparkles size={10} /> Or try one of these
              </p>
              <div className="grid grid-cols-1 gap-2">
                {STARTER_QUESTIONS.map((q, i) => (
                  <button key={i} onClick={() => sendMessage(q)}
                    className="text-left text-xs px-3 py-2.5 rounded-lg border border-[#21262D] text-[#7D8590]
                      hover:border-[#2563EB] hover:text-[#E6EDF3] transition-all bg-[#161B22]">
                    {q}
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <div className="space-y-5">
            {messages.map(msg => (
              <MessageBubble key={msg.id} message={msg} onFollowUp={sendMessage} />
            ))}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      <div className="px-5 py-4 border-t border-[#21262D] bg-[#0D1117]">
        <div className="flex gap-3 items-end">
          <div className="flex-1 relative">
            <textarea
              ref={inputRef}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKey}
              placeholder={activeReport ? `Ask about ${activeReport.name}...` : 'Ask a question...'}
              rows={1}
              disabled={loading}
              className="w-full bg-[#161B22] border border-[#21262D] rounded-xl px-4 py-3 text-sm
                text-[#E6EDF3] placeholder-[#7D8590] resize-none outline-none
                focus:border-[#2563EB] transition-colors disabled:opacity-50
                min-h-[44px] max-h-32 overflow-y-auto"
              onInput={e => { e.target.style.height = 'auto'; e.target.style.height = e.target.scrollHeight + 'px' }}
            />
          </div>
          <button onClick={() => sendMessage()} disabled={!input.trim() || loading}
            className="w-11 h-11 rounded-xl bg-[#2563EB] flex items-center justify-center flex-shrink-0
              hover:bg-[#1D4ED8] disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
            <Send size={15} className="text-white" />
          </button>
        </div>
        <p className="text-[10px] text-[#7D8590] mt-2 text-center">Press Enter to send · Shift+Enter for new line</p>
      </div>
    </div>
  )
}