import { Dialogue } from '../features/dialogue/Dialogue'
import { SessionList } from '../features/sessions/SessionList'
import { useSessions } from '../features/sessions/useSessions'
import '../features/dialogue/dialogue.css'

/** 页面只负责侧栏、会话标题与内容区域的布局。 */
export function HomePage() {
  const sessions = useSessions()
  const selected = sessions.sessions.find(
    (item) => item.id === sessions.selected,
  )
  return (
    <div className="app-shell">
      <header className="app-header">
        <a className="brand" href="/">
          Dialogue Lab
        </a>
        <span className="stage-label">说话、倾听、继续交流</span>
      </header>
      <div className="workspace">
        <aside className="session-sidebar">
          <SessionList
            {...sessions}
            onSelect={sessions.select}
            onCreate={sessions.create}
          />
        </aside>
        <main className="conversation-area">
          <header className="conversation-header">
            <p className="eyebrow">DIALOGUE</p>
            <h1>
              {selected?.title ??
                (sessions.selected ? '会话' : '从一次交流开始。')}
            </h1>
          </header>
          {sessions.selected ? (
            <Dialogue key={sessions.selected} sessionId={sessions.selected} />
          ) : (
            <div className="empty-session">
              <p>新建会话或选择已有会话，就可以开始说话，也可以输入文字。</p>
              <p>每次交流都会保存，你可以随时回来继续。</p>
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
