import * as vscode from "vscode";
import { SpeechFilter } from "./speechFilter";

/** 回消息给设备侧的通道（由 BridgeServer 注入） */
export interface ReplySink {
  send(obj: unknown): void;
}

const SYSTEM_PROMPT = [
  "你是通过「小智」智能音箱与用户语音对话的助手，回答会被 TTS 朗读成语音。",
  "规则：",
  "1. 只用口语化短句回答；不要使用 Markdown、标题、列表、代码块、表格、表情或链接；",
  "2. 涉及代码或文件时，用一两句话概括关键结论，不要朗读代码细节；",
  "3. 保持简短（一般不超过 200 字），除非用户明确要求详细；",
  "4. 除非用户使用其他语言，否则用中文回答。",
].join("\n");

interface DeviceRequest {
  sink: ReplySink;
  requestId: string;
  sessionId: string;
  text: string;
  filter: SpeechFilter;
  /** 已发给设备的播报文本（过滤后） */
  spoken: string;
  abort: vscode.CancellationTokenSource;
  finished: boolean;
}

interface PendingEntry {
  ctx: DeviceRequest;
  text: string;
  timer?: NodeJS.Timeout;
}

/**
 * 桥接核心：
 * - 设备请求 → 优先镜像到 @xiaozhi 聊天面板（可见）；注入失败/超时回退直连模型
 * - 流式输出经 SpeechFilter 过滤后发给设备；原始文本进入该 session 的历史（多轮）
 * - session_id = <device-id>#copilot，由服务端下发
 */
export class BridgeCore implements vscode.Disposable {
  private readonly sessions = new Map<string, vscode.LanguageModelChatMessage[]>();
  private readonly active = new Map<string, DeviceRequest>();
  private pending: PendingEntry[] = [];

  constructor(private readonly log: (line: string) => void) {}

  handleDeviceRequest(sink: ReplySink, requestId: string, sessionId: string, text: string): void {
    const cfg = vscode.workspace.getConfiguration("xiaozhiBridge");
    const ctx: DeviceRequest = {
      sink,
      requestId,
      sessionId,
      text,
      filter: new SpeechFilter(cfg.get<number>("spokenMaxChars", 300)),
      spoken: "",
      abort: new vscode.CancellationTokenSource(),
      finished: false,
    };
    this.active.set(requestId, ctx);
    this.log(`[设备请求] ${sessionId} → ${text}`);

    if (cfg.get<boolean>("mirrorToChat", true)) {
      void this.tryMirror(ctx);
    } else {
      void this.runDirect(ctx);
    }
  }

  cancel(requestId: string): void {
    this.pending = this.pending.filter((p) => {
      if (p.ctx.requestId === requestId) {
        if (p.timer) {
          clearTimeout(p.timer);
        }
        return false;
      }
      return true;
    });
    const ctx = this.active.get(requestId);
    if (!ctx) {
      return;
    }
    ctx.finished = true;
    ctx.abort.cancel();
    this.active.delete(requestId);
    this.log(`[取消] ${requestId}`);
  }

  /** 聊天参与者入口调用：认领对应的设备请求（按文本匹配；没有则视为手动聊天） */
  takePending(prompt: string): DeviceRequest | undefined {
    const idx = this.pending.findIndex((p) => p.text === prompt);
    if (idx < 0) {
      return undefined;
    }
    const [entry] = this.pending.splice(idx, 1);
    if (entry.timer) {
      clearTimeout(entry.timer);
    }
    return entry.ctx;
  }

  /** 镜像路径：在聊天面板里回答（可见），同时播报到设备 */
  async runMirrored(
    ctx: DeviceRequest,
    model: vscode.LanguageModelChat,
    stream: vscode.ChatResponseStream,
    token: vscode.CancellationToken
  ): Promise<void> {
    const linked = new vscode.CancellationTokenSource();
    token.onCancellationRequested(() => linked.cancel());
    ctx.abort.token.onCancellationRequested(() => linked.cancel());
    await this.runWithModel(ctx, model, (fragment) => stream.markdown(fragment), linked.token);
    if (!ctx.finished && !ctx.spoken) {
      stream.markdown("（本次没有可播报的内容）");
    }
  }

  dispose(): void {
    for (const ctx of this.active.values()) {
      ctx.abort.cancel();
    }
    this.active.clear();
    this.pending = [];
  }

  // ------------------------------------------------------------------
  // 内部实现
  // ------------------------------------------------------------------

  private async tryMirror(ctx: DeviceRequest): Promise<void> {
    try {
      await vscode.commands.executeCommand("workbench.action.chat.open", {
        query: `@xiaozhi ${ctx.text}`,
        isPartialQuery: false,
      });
    } catch (e) {
      this.log(`[镜像注入失败] ${String(e)}；回退直连模型`);
      void this.runDirect(ctx);
      return;
    }
    const entry: PendingEntry = { ctx, text: ctx.text };
    this.pending.push(entry);
    const waitMs = vscode.workspace.getConfiguration("xiaozhiBridge").get<number>("mirrorPickupMs", 2000);
    entry.timer = setTimeout(() => {
      this.pending = this.pending.filter((p) => p !== entry);
      if (!ctx.finished) {
        this.log("[镜像超时] 聊天参与者未接管，回退直连模型");
        void this.runDirect(ctx);
      }
    }, waitMs);
  }

  private async runDirect(ctx: DeviceRequest): Promise<void> {
    if (ctx.finished) {
      return;
    }
    const family = vscode.workspace.getConfiguration("xiaozhiBridge").get<string>("modelFamily", "");
    const models = await vscode.lm.selectChatModels(family ? { vendor: "copilot", family } : { vendor: "copilot" });
    const model = models[0];
    if (!model) {
      this.failRequest(ctx, new Error("找不到可用的 Copilot 模型（请确认已登录并启用 GitHub Copilot）"));
      return;
    }
    await this.runWithModel(ctx, model, undefined, ctx.abort.token);
  }

  private async runWithModel(
    ctx: DeviceRequest,
    model: vscode.LanguageModelChat,
    mirror: ((fragment: string) => void) | undefined,
    token: vscode.CancellationToken
  ): Promise<void> {
    const messages = this.buildMessages(ctx.sessionId, ctx.text);
    let raw = "";
    try {
      const response = await model.sendRequest(messages, {}, token);
      for await (const fragment of response.text) {
        if (ctx.finished) {
          return;
        }
        raw += fragment;
        mirror?.(fragment);
        const spoken = ctx.filter.push(fragment);
        if (spoken) {
          this.sendChunk(ctx, spoken);
        }
      }
      if (ctx.finished) {
        return;
      }
      const tail = ctx.filter.flush();
      if (tail) {
        this.sendChunk(ctx, tail);
      }
      this.finishRequest(ctx, raw);
    } catch (e) {
      if (ctx.finished || e instanceof vscode.CancellationError) {
        return;
      }
      this.failRequest(ctx, e);
    }
  }

  private buildMessages(sessionId: string, text: string): vscode.LanguageModelChatMessage[] {
    let history = this.sessions.get(sessionId);
    if (!history) {
      history = [vscode.LanguageModelChatMessage.User(SYSTEM_PROMPT)];
      this.sessions.set(sessionId, history);
    }
    history.push(vscode.LanguageModelChatMessage.User(text));
    if (history.length > 21) {
      history.splice(1, history.length - 21); // 始终保留 system + 最近 20 条
    }
    return history.slice();
  }

  private sendChunk(ctx: DeviceRequest, text: string): void {
    ctx.spoken += text;
    try {
      ctx.sink.send({ type: "chunk", request_id: ctx.requestId, text });
    } catch {
      /* 设备侧已断开，忽略 */
    }
  }

  private finishRequest(ctx: DeviceRequest, raw: string): void {
    if (ctx.finished) {
      return;
    }
    ctx.finished = true;
    this.active.delete(ctx.requestId);
    if (raw.trim()) {
      this.sessions.get(ctx.sessionId)?.push(vscode.LanguageModelChatMessage.Assistant(raw));
    }
    try {
      ctx.sink.send({ type: "done", request_id: ctx.requestId, text: ctx.spoken });
    } catch {
      /* 忽略 */
    }
    this.log(`[已回复] ${ctx.sessionId} ← ${ctx.spoken.slice(0, 80)}`);
  }

  private failRequest(ctx: DeviceRequest, e: unknown): void {
    if (ctx.finished) {
      return;
    }
    ctx.finished = true;
    this.active.delete(ctx.requestId);
    const message = this.errorText(e);
    try {
      ctx.sink.send({ type: "error", request_id: ctx.requestId, message });
    } catch {
      /* 忽略 */
    }
    this.log(`[错误] ${message}`);
  }

  private errorText(e: unknown): string {
    if (e instanceof vscode.LanguageModelError) {
      switch (e.code) {
        case "Blocked":
          return "额度受限（可能已达配额上限）";
        case "NoPermissions":
          return "未授权使用 Copilot（请允许扩展访问语言模型）";
        case "NotFound":
          return "模型不可用";
        default:
          return `语言模型错误（${e.code}）`;
      }
    }
    return e instanceof Error ? e.message : String(e);
  }
}
