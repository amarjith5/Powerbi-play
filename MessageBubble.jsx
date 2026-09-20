import { Bot, User, Database } from 'lucide-react'
import InlineChart from './InlineChart'

function TypingIndicator() {
  return (
    <div className="flex items-end gap-2 msg-enter">
      <div className="w-7 h-7 rounded-full bg-[#2563EB] flex items-center justify-center flex-shrink-0">
        <Bot size={14} className="text-white" />
      </div>
      <div className="bg-[#161B22] border border-[#21262D] rounded-2xl rounded-bl-sm px-4 py-3">
        <div className="flex gap-1 items-center h-4">
          <div className="dot w-1.5 h-1.5 bg-[#7D8590] rounded-full" />
          <div className="dot w-1.5 h-1.5 bg-[#7D8590] rounded-full" />
          <div className="dot w-1.5 h-1.5 bg-[#7D8590] rounded-full" />
        </div>
      </div>
    </div>
  )
}

export default function MessageBubble({ message, onFollowUp }) {
  if (message.typing) return <TypingIndicator />
  const isUser = message.role === 'user'

  return (
    <div className={`flex items-end gap-2 msg-enter ${isUser ? 'flex-row-reverse' : ''}`}>
      <div className={`w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0 mb-0.5
        ${isUser ? 'bg-[#21262D]' : 'bg-[#2563EB]'}`}>
        {isUser ? <User size={13} className="text-[#7D8590]" /> : <Bot size={13} className="text-white" />}
      </div>

      <div className={`max-w-[78%] ${isUser ? 'items-end' : 'items-start'} flex flex-col gap-1`}>
        <div className={`px-4 py-3 rounded-2xl text-sm leading-relaxed
          ${isUser
            ? 'bg-[#2563EB] text-white rounded-br-sm'
            : 'bg-[#161B22] border border-[#21262D] text-[#E6EDF3] rounded-bl-sm'
          }`}>
          {message.content}
          {!isUser && message.chart && <InlineChart chart={message.chart} />}
          {!isUser && message.data_used && (
            <div className="flex items-center gap-1 mt-2 pt-2 border-t border-[#21262D]">
              <Database size={9} className="text-[#7D8590]" />
              <span className="text-[9px] text-[#7D8590] font-mono">{message.data_used}</span>
            </div>
          )}
        </div>

        {!isUser && message.follow_up_questions?.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-1">
            {message.follow_up_questions.map((q, i) => (
              <button key={i} onClick={() => onFollowUp(q)}
                className="text-[10px] px-2.5 py-1 rounded-full border border-[#21262D] text-[#7D8590]
                  hover:border-[#2563EB] hover:text-[#2563EB] transition-colors bg-[#0D1117]">
                {q}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}