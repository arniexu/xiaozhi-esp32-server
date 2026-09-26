import { WebSocketServer, WebSocket } from "ws";
import { BridgeCore } from "./bridgeCore";

interface InboundMessage {
  type?: string;
  request_id?: string;
  session_id?: string;
  text?: string;
}

/**
 * 桥接 WebSocket 服务（仅绑定 127.0.0.1）。
 * 协议（JSON 单行）：
 *   服务端→扩展: {"type":"request","request_id","session_id","text"} / {"type":"cancel","request_id"} / {"type":"ping"}
 *   扩展→服务端: {"type":"chunk"|"done"|"error","request_id","text"|"message"}
 */
export class BridgeServer {
  private wss?: WebSocketServer;
  private clients = 0;

  constructor(
    private readonly core: BridgeCore,
    private readonly output: (line: string) => void,
    private readonly onClientsChanged: (n: number) => void
  ) {}

  start(port: number, host = "127.0.0.1"): void {
    this.stop();
    const wss = new WebSocketServer({ host, port });
    wss.on("listening", () => this.output(`[桥接服务] 监听 ws://${host}:${port}`));
    wss.on("error", (e) => this.output(`[桥接服务] 错误: ${String(e)}（端口被占用？可在设置里修改 xiaozhiBridge.port）`));
    wss.on("connection", (ws) => {
      this.clients += 1;
      this.onClientsChanged(this.clients);
      this.output(`[桥接服务] 设备侧已连接（当前 ${this.clients}）`);
      ws.on("message", (data) => this.onMessage(ws, data.toString()));
      ws.on("close", () => {
        this.clients = Math.max(0, this.clients - 1);
        this.onClientsChanged(this.clients);
      });
      ws.on("error", () => {
        /* 忽略单连接错误 */
      });
    });
    this.wss = wss;
  }

  stop(): void {
    try {
      this.wss?.close();
    } catch {
      /* 忽略 */
    }
    this.wss = undefined;
  }

  dispose(): void {
    this.stop();
  }

  private onMessage(ws: WebSocket, raw: string): void {
    let msg: InboundMessage;
    try {
      msg = JSON.parse(raw) as InboundMessage;
    } catch {
      this.output("[桥接服务] 收到非法 JSON，已忽略");
      return;
    }
    const sink = { send: (obj: unknown) => this.safeSend(ws, obj) };
    switch (msg.type) {
      case "request":
        this.core.handleDeviceRequest(
          sink,
          String(msg.request_id ?? ""),
          String(msg.session_id ?? "default"),
          String(msg.text ?? "")
        );
        break;
      case "cancel":
        this.core.cancel(String(msg.request_id ?? ""));
        break;
      case "ping":
        this.safeSend(ws, { type: "pong" });
        break;
      default:
        this.output(`[桥接服务] 未知消息类型: ${String(msg.type)}`);
    }
  }

  private safeSend(ws: WebSocket, obj: unknown): void {
    try {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(obj));
      }
    } catch {
      /* 忽略 */
    }
  }
}
