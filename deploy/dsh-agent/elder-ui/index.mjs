/**
 * elder-ui —— elder_helper（web 档）的两个小改造：
 *
 * 1) 把 agent 收到的请求实时打出来
 *    挂 `agent/pre-step`，每次模型推理前取最后一条 user 消息，追加到
 *    ~/.dsh/logs/elder-prompts.log，同时写一份到 dsh 进程 stdout（前台可见）。
 *
 * 2) 老人友好的界面微调
 *    通过 webServer.tapIndex 往页面注入一段 CSS：放大字号/行高、按钮加大、
 *    输入框更易读。纯 CSS，不碰组件逻辑，刷新页面即生效。
 *
 * 挂载（~/.dsh/profiles/elder_helper/cordis.patch.yml）：
 *   - insert:
 *       - id: elder-ui
 *         name: file:///home/xuqj/.dsh/plugins/elder-ui/index.mjs
 */
import fs from 'node:fs'
import path from 'node:path'
import os from 'node:os'
import { fileURLToPath } from 'node:url'

export const name = 'elder-ui'
export const inject = ['webServer']

const LOG = path.join(os.homedir(), '.dsh', 'logs', 'elder-prompts.log')
const SELF_LOG = path.join(os.homedir(), '.dsh', 'logs', 'elder-ui.log')
const CSS_FILE = path.join(path.dirname(fileURLToPath(import.meta.url)), 'elder-ui.css')

function note(message) {
  const line = `${new Date().toISOString()} ${message}`
  try {
    fs.mkdirSync(path.dirname(SELF_LOG), { recursive: true })
    fs.appendFileSync(SELF_LOG, `${line}\n`)
  } catch {}
}

function stamp() {
  const now = new Date()
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`
}

/** 从一条消息里抽出纯文本（content 可能是字符串，也可能是 content block 数组）。 */
function textOf(message) {
  const content = message && message.content
  if (typeof content === 'string') return content.trim()
  if (Array.isArray(content)) {
    return content
      .filter((block) => block && (block.type === 'text' || typeof block.text === 'string'))
      .map((block) => String(block.text || ''))
      .join('')
      .trim()
  }
  return ''
}

const sessionIds = new WeakMap()

/** 会话标签：优先用 agent/created 里记下的 id，取不到就留空（不打印难看的占位）。 */
function sessionLabel(agent) {
  const id = sessionIds.get(agent) || agent?.id || agent?.sessionId || ''
  return String(id).replace(/^session-/, '').slice(0, 8)
}


export function apply(ctx) {
  try {
    // agent/pre-step 是 waterfall 事件：必须把 next() 的返回值原样透传，
    // 否则后面的推理链拿不到上下文（实测表现为 "Cannot read properties of undefined (reading 'kind')"）
    ctx.on('agent/pre-step', (payload, next) => {
      try {
        const { agent, messages } = payload || {}
        if (Array.isArray(messages)) {
          const lastUser = [...messages].reverse().find((m) => m && m.role === 'user')
          const text = lastUser ? textOf(lastUser) : ''
          if (text) {
            const label = sessionLabel(agent)
            const prefix = label ? `${label} ` : ''
            const line = `[${stamp()}] ${prefix}用户: ${text.replace(/\s+/g, ' ').slice(0, 500)}`
            try {
              fs.mkdirSync(path.dirname(LOG), { recursive: true })
              fs.appendFileSync(LOG, `${line}\n`)
            } catch (err) {
              note(`写请求日志失败: ${err}`)
            }
            // 同时打到 dsh 进程的 stdout：前台运行时能直接看到
            try {
              process.stdout.write(`${line}\n`)
            } catch {}
          }
        }
      } catch (err) {
        note(`pre-step 处理异常: ${err}`)
      }
      return next()
    })
    // 记下 agent → sessionId，日志里就能标出是哪条会话
    try {
      ctx.on('agent/created', (payload) => {
        const agent = payload?.agent
        const id = payload?.id || payload?.sessionId || agent?.id || agent?.sessionId
        if (agent && id) sessionIds.set(agent, String(id))
      })
    } catch (err) {
      note(`挂 agent/created 失败: ${err}`)
    }
    note('已挂 agent/pre-step 请求日志')
  } catch (err) {
    note(`挂事件失败: ${err}`)
  }

  try {
    if (typeof ctx.webServer?.tapIndex === 'function') {
      ctx.webServer.tapIndex((html) => {
        // 每次请求都重读 CSS：调样式只刷新页面，不用重启 dsh
        let css = ''
        try {
          css = fs.readFileSync(CSS_FILE, 'utf8')
        } catch (err) {
          note(`读 ${CSS_FILE} 失败: ${err}`)
          return html
        }
        const tag = `<style data-elder-ui>\n${css}\n</style>`
        return html.includes('</head>') ? html.replace('</head>', `${tag}</head>`) : tag + html
      })
      note(`已注入 elder-ui CSS（来自 ${CSS_FILE}）`)
    }
  } catch (err) {
    note(`注入 CSS 失败: ${err}`)
  }
}
