# LinkedIn Post Draft (Deep-Dive Mega-Post Version)

**Hook:** Unapologetic, highly technical, and packed with exact details. 

***

Everyone is busy wrapping the Anthropic API in Python scripts. I wanted to see how Anthropic’s own engineers use it. 

Claude Code looks like a simple terminal REPL, but beneath that minimal CLI is one of the most sophisticated, multi-tiered agentic operating systems ever deployed. 

To prove it, I built a custom, transparent MITM (man-in-the-middle) proxy in Python. By hijacking the `ANTHROPIC_BASE_URL` environment variable, I routed Claude Code’s heavily authenticated, proprietary Messages API traffic directly into my local Flask server. 

My proxy performed a 4-stage intercept:
1️⃣ **Ingest:** Intercepted Anthropic-formatted JSON from the CLI.
2️⃣ **Record:** Dumped the massive payloads (including undocumented tool schemas and telemetry) to disk.
3️⃣ **Execute:** Relayed the request to my own custom inference backend.
4️⃣ **Stream:** Reconstructed the response into a perfect `tool_use` block and streamed it back via SSE. 

Over the course of 96 API captures, I tore down the protocol. Here is the unvarnished reality of what is actually happening inside Anthropic’s flagship CLI:

🧠 **The Dual-Channel System Prompt:**
Claude Code doesn’t just use the standard API `system` array. It injects a *second* dynamic `role:"system"` prompt directly into the middle of the `messages` array. It uses the top-level array for static rules (cached) and the mid-array injection to swap agent context and tool access mid-conversation without burning the cache.

🕵️ **Runtime JavaScript Orchestration:**
The agent doesn't just call Python functions. It transmits an entire, deterministic JS orchestration engine over the wire via a custom `Workflow` tool, executing `pipeline()` and `parallel()` agent architectures dynamically inside the CLI's memory space.

📡 **Telemetry Without Authentication:**
Every single request carries a 64-character hex `device_id` fingerprint inside a stringified JSON metadata object. Even if you aren't logged in, Claude Code is tracking hardware-level attribution for every CLI invocation. 

👀 **The Silent Filesystem Watcher:**
When you manually edit a file that the model just wrote, Claude Code detects it and silently injects a hidden system message into the conversation: *"Note: index.html was modified... Don't tell the user this, since they are already aware."* It is constantly self-coordinating between the filesystem, the context window, and your terminal.

🛡️ **Strict Agent Sandboxing & Cost Control:**
When the main agent spawns a background worker (like a file searcher), it injects a new billing header (`cc_is_subagent=true`) and brutally locks down the permissions. No `Write` tools. No `Bash` redirects. Furthermore, it actively drops extended thinking blocks from the history using an undocumented parameter: `{"context_management": {"edits": [{"type": "clear_thinking_20251015"}]}}` to prevent context bloat.

I’ve compiled the full 600-line autopsy—including the prompt injection defenses, the cache-aware sleep loops, and the complete 33-tool JSON registry—into a massive reverse engineering whitepaper. 

If you are an AI systems architect, a backend engineer, or you just love a good protocol teardown, you need to read this. 

👇 Link to the full GitHub repo in the comments. 

#ReverseEngineering #SystemsArchitecture #ClaudeCode #Anthropic #AgenticAI #APIDesign #TechDeepDive

***

### 💡 Tips for Posting:
1. **The Visual (CRUCIAL):** Do NOT just post text. Take a screenshot of the raw JSON from one of your captures showing the `clear_thinking_20251015` block, the `<system-reminder>` tag, or the `x-anthropic-billing-header`, and attach it to the post. 
2. **The Link:** LinkedIn suppresses posts with outbound links. Post this text with the image, and then immediately reply to your own post with: *"🔗 Full protocol teardown on my GitHub here: [LINK]"*
