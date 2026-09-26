import * as vscode from "vscode";
import { BridgeCore } from "./bridgeCore";
import { BridgeServer } from "./bridgeServer";

export function activate(context: vscode.ExtensionContext): void {
  const output = vscode.window.createOutputChannel("小智桥接");
  const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 90);
  const core = new BridgeCore((line) => output.appendLine(line));

  let clients = 0;
  let server: BridgeServer | undefined;

  const getPort = (): number => vscode.workspace.getConfiguration("xiaozhiBridge").get<number>("port", 8767);

  const updateStatus = (): void => {
    status.text = `$(radio-tower) 小智桥接:${getPort()}${clients > 0 ? ` (${clients})` : ""}`;
    status.tooltip = "小智 Copilot 桥接：设备 ⇄ VS Code Copilot（点击查看状态）";
    status.command = "xiaozhiBridge.showStatus";
    status.show();
  };

  const startServer = (): void => {
    server?.dispose();
    server = new BridgeServer(
      core,
      (line) => output.appendLine(line),
      (n) => {
        clients = n;
        updateStatus();
      }
    );
    server.start(getPort());
    updateStatus();
  };

  startServer();
  output.appendLine(`[启动] 小智 Copilot 桥接 v${String(context.extension.packageJSON.version ?? "?")}`);
  output.appendLine(`[启动] 桥接监听 127.0.0.1:${getPort()}；xiaozhi-server 的 copilot_bridge.url 需与之对应`);
  output.appendLine("[启动] 首次对话时 Copilot 会请求授权扩展访问语言模型，请选择允许");

  // @xiaozhi 聊天参与者：设备请求的镜像入口（也可手动聊天）
  const participant = vscode.chat.createChatParticipant("xiaozhi.bridge", async (request, _ctx, stream, token) => {
    const deviceCtx = core.takePending(request.prompt);
    if (deviceCtx) {
      await core.runMirrored(deviceCtx, request.model, stream, token);
      return {};
    }
    // 手动聊天（与设备无关）
    if (!request.prompt.trim()) {
      stream.markdown("桥接已就绪。设备说「**问 Copilot …**」即可开始；也可以在这里直接和我聊天。");
      return {};
    }
    try {
      const messages = [vscode.LanguageModelChatMessage.User(request.prompt)];
      const response = await request.model.sendRequest(messages, {}, token);
      for await (const fragment of response.text) {
        stream.markdown(fragment);
      }
    } catch (e) {
      if (e instanceof vscode.CancellationError) {
        return {};
      }
      stream.markdown(`⚠️ ${e instanceof Error ? e.message : String(e)}`);
    }
    return {};
  });

  context.subscriptions.push(status, output, core, participant);
  context.subscriptions.push({ dispose: () => server?.dispose() });
  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration("xiaozhiBridge.port")) {
        startServer();
      }
    })
  );
  context.subscriptions.push(
    vscode.commands.registerCommand("xiaozhiBridge.showStatus", () => {
      output.show(true);
      output.appendLine(
        `[状态] 端口 ${getPort()}，当前连接 ${clients}，镜像=${vscode.workspace
          .getConfiguration("xiaozhiBridge")
          .get<boolean>("mirrorToChat", true)}`
      );
    })
  );
  context.subscriptions.push(
    vscode.commands.registerCommand("xiaozhiBridge.restart", () => {
      startServer();
      output.appendLine("[状态] 桥接服务已重启");
    })
  );
}

export function deactivate(): void {
  /* disposables 由 VS Code 统一回收 */
}
