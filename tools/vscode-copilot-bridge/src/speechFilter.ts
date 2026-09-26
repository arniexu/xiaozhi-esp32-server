/**
 * 播报过滤器：把 LLM 流式 Markdown 文本转成适合 TTS 朗读的文本。
 *
 * - 代码围栏 ```...``` → 「（代码部分略过）」；行内反引号去壳保留内容
 * - 去掉 Markdown 记号（#、*、_、>）、图片、链接语法（保留链接文字）
 * - 空白/换行压缩（换行 → 句号），超长按 maxChars 截断并追加省略号
 * - 按增量流式调用 push()，结束时调用 flush()
 */
export class SpeechFilter {
  /** 尚未处理的尾部字符（防止 ``` 等记号跨 chunk 被截断） */
  private raw = "";
  private inFence = false;
  private emitted = 0;
  private truncated = false;

  constructor(private readonly maxChars: number) {}

  push(chunk: string): string {
    if (this.truncated) {
      return "";
    }
    this.raw += chunk;
    // 保留尾部少量字符，避免 ``` 等记号跨 chunk 被拆散；
    // 若截断点落在反引号连跑内部，则退到整段连跑之前一并保留
    let cut = Math.max(0, this.raw.length - 2);
    while (cut > 0 && this.raw[cut - 1] === "`") {
      cut -= 1;
    }
    const text = this.raw.slice(0, cut);
    this.raw = this.raw.slice(cut);
    return this.process(text);
  }

  flush(): string {
    if (this.truncated) {
      return "";
    }
    const text = this.raw;
    this.raw = "";
    return this.process(text);
  }

  private process(text: string): string {
    if (!text) {
      return "";
    }
    let out = "";
    let i = 0;
    while (i < text.length) {
      if (this.inFence) {
        const end = text.indexOf("```", i);
        if (end === -1) {
          break; // 仍在代码块内，丢弃
        }
        this.inFence = false;
        i = end + 3;
        out += "（代码部分略过）";
        continue;
      }
      const fence = text.indexOf("```", i);
      const segment = fence === -1 ? text.slice(i) : text.slice(i, fence);
      out += this.clean(segment);
      if (fence === -1) {
        i = text.length;
      } else {
        this.inFence = true;
        i = fence + 3;
      }
    }
    return this.finish(out);
  }

  private clean(s: string): string {
    return s
      .replace(/`([^`]*)`/g, "$1")
      .replace(/!\[[^\]]*\]\([^)]*\)/g, "")
      .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
      .replace(/^#{1,6}\s+/gm, "")
      .replace(/^\s*[-+*]\s+/gm, "")
      .replace(/[*_`#>]/g, "")
      .replace(/[ \t]+/g, " ")
      .replace(/\s*\n\s*/g, "。");
  }

  private finish(out: string): string {
    if (!out) {
      return "";
    }
    const remain = this.maxChars - this.emitted;
    if (remain <= 0) {
      if (!this.truncated) {
        this.truncated = true;
        return "……";
      }
      return "";
    }
    if (out.length > remain) {
      this.emitted = this.maxChars;
      this.truncated = true;
      return out.slice(0, remain) + "……";
    }
    this.emitted += out.length;
    return out;
  }
}
