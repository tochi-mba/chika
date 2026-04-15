"""
Chika v2 — API documentation page served at /readme
"""

README_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Chika v2 — API Docs</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #0d0d12;
    color: #c8c8d8;
    display: flex;
    height: 100vh;
    overflow: hidden;
    font-size: 14px;
    line-height: 1.6;
  }

  /* ── Sidebar ── */
  nav {
    width: 240px;
    flex-shrink: 0;
    background: #0b0b10;
    border-right: 1px solid #1e1e2a;
    overflow-y: auto;
    padding: 20px 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  nav::-webkit-scrollbar { width: 4px; }
  nav::-webkit-scrollbar-thumb { background: #2a2a38; border-radius: 2px; }

  .nav-brand {
    padding: 0 16px 16px;
    border-bottom: 1px solid #1e1e2a;
    margin-bottom: 8px;
  }
  .nav-brand h1 { font-size: 16px; font-weight: 700; color: #e8e8f0; }
  .nav-brand span { font-size: 11px; color: #444; }

  .nav-section {
    padding: 6px 16px 2px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #333;
    margin-top: 8px;
  }
  nav a {
    display: block;
    padding: 5px 16px 5px 20px;
    color: #666;
    text-decoration: none;
    font-size: 13px;
    border-left: 2px solid transparent;
    transition: color 0.1s, border-color 0.1s, background 0.1s;
  }
  nav a:hover { color: #aaa; background: #12121a; }
  nav a.active { color: #a78bff; border-left-color: #7c6fff; background: #14141f; }

  /* ── Main ── */
  main {
    flex: 1;
    overflow-y: auto;
    padding: 40px 48px;
    max-width: 860px;
  }
  main::-webkit-scrollbar { width: 6px; }
  main::-webkit-scrollbar-thumb { background: #2a2a38; border-radius: 3px; }

  section { margin-bottom: 56px; scroll-margin-top: 24px; }

  h2 {
    font-size: 22px;
    font-weight: 700;
    color: #e8e8f0;
    margin-bottom: 16px;
    padding-bottom: 10px;
    border-bottom: 1px solid #1e1e2a;
  }
  h3 {
    font-size: 15px;
    font-weight: 600;
    color: #d0d0e0;
    margin: 24px 0 10px;
  }
  h4 {
    font-size: 13px;
    font-weight: 600;
    color: #b0b0c8;
    margin: 16px 0 6px;
  }
  p { margin-bottom: 10px; color: #909098; }

  /* ── Code ── */
  pre {
    background: #0a0a0f;
    border: 1px solid #1e1e2a;
    border-radius: 8px;
    padding: 16px;
    overflow-x: auto;
    margin: 10px 0 16px;
    font-size: 12.5px;
    line-height: 1.55;
  }
  pre::-webkit-scrollbar { height: 4px; }
  pre::-webkit-scrollbar-thumb { background: #2a2a38; }

  code {
    font-family: 'Fira Code', 'Cascadia Code', 'JetBrains Mono', Consolas, monospace;
    font-size: 12.5px;
  }
  p code, li code, td code {
    background: #141420;
    border: 1px solid #1e1e2a;
    border-radius: 4px;
    padding: 1px 5px;
    color: #a78bff;
    font-size: 12px;
  }

  /* Syntax colors */
  .k  { color: #7c6fff; } /* keyword / type */
  .s  { color: #56d364; } /* string */
  .n  { color: #79c0ff; } /* name / key */
  .c  { color: #484860; } /* comment */
  .p  { color: #c8c8d8; } /* punctuation */
  .nb { color: #ffa657; } /* number / bool */

  /* ── Badges ── */
  .method {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 700;
    font-family: monospace;
    margin-right: 8px;
  }
  .get    { background: #0d3a1a; color: #56d364; border: 1px solid #1a5a28; }
  .post   { background: #1a2a0d; color: #a78bff; border: 1px solid #2a3a1a; }
  .delete { background: #3a0d0d; color: #f85149; border: 1px solid #5a1a1a; }
  .ws-badge { background: #0d1a3a; color: #79c0ff; border: 1px solid #1a2a5a; }

  /* ── Event table ── */
  .event-table { width: 100%; border-collapse: collapse; margin: 10px 0; }
  .event-table th {
    text-align: left;
    padding: 8px 12px;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #444;
    border-bottom: 1px solid #1e1e2a;
  }
  .event-table td {
    padding: 8px 12px;
    border-bottom: 1px solid #141420;
    vertical-align: top;
    font-size: 12.5px;
  }
  .event-table tr:last-child td { border-bottom: none; }
  .event-table tr:hover td { background: #0f0f18; }
  .event-type { color: #79c0ff; font-family: monospace; font-weight: 600; }

  /* ── Callout ── */
  .callout {
    background: #0d1a2e;
    border: 1px solid #1a3050;
    border-left: 3px solid #79c0ff;
    border-radius: 6px;
    padding: 12px 16px;
    margin: 12px 0;
    font-size: 13px;
    color: #8a9ab8;
  }
  .callout.warn {
    background: #1e1400;
    border-color: #3a2800;
    border-left-color: #ffa657;
    color: #a88b60;
  }

  /* ── Flow steps ── */
  .flow {
    counter-reset: flow;
    list-style: none;
    margin: 12px 0;
  }
  .flow li {
    counter-increment: flow;
    display: flex;
    gap: 12px;
    margin-bottom: 10px;
    font-size: 13px;
    color: #909098;
  }
  .flow li::before {
    content: counter(flow);
    flex-shrink: 0;
    width: 22px; height: 22px;
    background: #1a1a2a;
    border: 1px solid #2a2a3a;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 11px;
    font-weight: 700;
    color: #7c6fff;
    margin-top: 1px;
  }

  /* ── Endpoint block ── */
  .endpoint {
    background: #0a0a0f;
    border: 1px solid #1e1e2a;
    border-radius: 8px;
    margin-bottom: 20px;
    overflow: hidden;
  }
  .endpoint-header {
    padding: 12px 16px;
    display: flex;
    align-items: center;
    gap: 8px;
    border-bottom: 1px solid #1e1e2a;
    background: #0d0d14;
  }
  .endpoint-path { font-family: monospace; color: #d0d0e0; font-size: 13px; }
  .endpoint-desc { font-size: 12px; color: #555; margin-left: auto; }
  .endpoint-body { padding: 12px 16px; }
  .endpoint-body p { font-size: 12.5px; }
</style>
</head>
<body>

<!-- ── Sidebar ── -->
<nav id="nav">
  <div class="nav-brand">
    <h1>⚡ Chika v2</h1>
    <span>API Reference</span>
  </div>

  <div class="nav-section">Overview</div>
  <a href="#overview">Introduction</a>
  <a href="#auth">Authentication</a>

  <div class="nav-section">WebSocket</div>
  <a href="#ws-connect">Connection &amp; Device Setup</a>
  <a href="#ws-flow">Connection Flow</a>
  <a href="#ws-server-events">Server → Client Events</a>
  <a href="#ws-client-msgs">Client → Server Messages</a>

  <div class="nav-section">REST API</div>
  <a href="#rest-health">Health</a>
  <a href="#rest-profiles">Profiles</a>
  <a href="#rest-chats">Chats</a>
  <a href="#rest-sessions">Sessions</a>
  <a href="#rest-config">Config &amp; Tools</a>
  <a href="#rest-spotify">Spotify OAuth</a>

  <div class="nav-section">Examples</div>
  <a href="#ex-python">Python Client</a>
  <a href="#ex-js">JavaScript Client</a>
  <a href="#ex-curl">cURL</a>
</nav>

<!-- ── Content ── -->
<main id="main">

<!-- ═══════════════════════════════════ OVERVIEW ═══════════════════════════════════ -->
<section id="overview">
  <h2>Introduction</h2>
  <p>Chika v2 is a streaming AI agent server. The primary interface is a <strong>WebSocket</strong> at <code>/ws/</code> that streams typed JSON events in real time. A set of REST endpoints expose metadata, session state, and chat history.</p>
  <p>The server binds to <code>0.0.0.0</code> so it is accessible on your LAN. Put it behind nginx + TLS or a Cloudflare Tunnel for public access.</p>

  <h3>Base URLs</h3>
  <pre><code><span class="c"># Local development</span>
<span class="n">HTTP</span>  <span class="p">→</span> <span class="s">http://localhost:8000</span>
<span class="n">WS</span>   <span class="p">→</span> <span class="s">ws://localhost:8000</span>

<span class="c"># LAN / production (example)</span>
<span class="n">HTTP</span>  <span class="p">→</span> <span class="s">https://chika.example.com</span>
<span class="n">WS</span>   <span class="p">→</span> <span class="s">wss://chika.example.com</span></code></pre>
</section>

<!-- ═══════════════════════════════════ AUTH ═══════════════════════════════════ -->
<section id="auth">
  <h2>Authentication</h2>
  <p>Auth is controlled by the <code>CHIKA_API_KEY</code> environment variable. If it is <strong>not set</strong>, all endpoints are open (local dev mode).</p>

  <h3>REST endpoints</h3>
  <p>Pass the key in the <code>Authorization</code> header:</p>
  <pre><code>Authorization: Bearer YOUR_API_KEY</code></pre>

  <h3>WebSocket</h3>
  <p>Browsers cannot set custom headers on WebSocket upgrades, so pass the key as a query parameter:</p>
  <pre><code>ws://localhost:8000/ws/?token=YOUR_API_KEY&amp;device=dev_abc123</code></pre>

  <div class="callout warn">
    The <code>/health</code> and <code>/readme</code> endpoints are always unauthenticated.
  </div>
</section>

<!-- ═══════════════════════════════════ WS CONNECT ═══════════════════════════════════ -->
<section id="ws-connect">
  <h2>WebSocket — Connection &amp; Device Setup</h2>

  <p>All real-time communication happens over a single WebSocket endpoint. The server identifies clients via an opaque <strong>device ID</strong> it generates and embeds in the first <code>session_info</code> event. The client must echo this token back on every reconnect.</p>

  <h3>Endpoint</h3>
  <pre><code><span class="k">WS</span>  /ws/

<span class="c"># Query parameters (all optional)</span>
<span class="n">token</span>   <span class="p">=</span> <span class="s">"YOUR_API_KEY"</span>   <span class="c"># required if CHIKA_API_KEY is set</span>
<span class="n">device</span>  <span class="p">=</span> <span class="s">"dev_abc123"</span>    <span class="c"># omit on first connection; echo back on reconnects</span></code></pre>

  <h3>Device ID lifecycle</h3>
  <ol class="flow">
    <li>Client connects to <code>/ws/</code> with no <code>device</code> param.</li>
    <li>Server generates a new <code>device_id</code> (e.g. <code>dev_a3f9c12b</code>) and creates a fresh chat session for it.</li>
    <li>Server immediately sends a <code>session_info</code> event containing <code>device_id</code>, <code>session_id</code>, the full message history (empty for new devices), and the current profile.</li>
    <li>Client <strong>stores <code>device_id</code></strong> (e.g. in <code>sessionStorage</code> or on disk for a CLI).</li>
    <li>On every subsequent connection — including after page refresh or server restart — the client passes <code>?device=dev_a3f9c12b</code>.</li>
    <li>Server looks up the device, finds its current session, restores history from disk if the server was restarted, and sends <code>session_info</code> again with full state.</li>
  </ol>

  <div class="callout">
    <strong>One device = one active chat at a time.</strong> The device can have many saved chats; the server remembers which one is current. Switching chats sends a <code>switch_chat</code> message.
  </div>
</section>

<!-- ═══════════════════════════════════ WS FLOW ═══════════════════════════════════ -->
<section id="ws-flow">
  <h2>WebSocket — Connection Flow</h2>

  <h3>On first connect (no device ID)</h3>
  <pre><code><span class="c"># Client opens:</span>
ws://localhost:8000/ws/

<span class="c"># Server sends immediately (in order):</span>
<span class="p">{</span> <span class="n">"type"</span><span class="p">:</span> <span class="s">"session_info"</span><span class="p">,</span> <span class="n">"device_id"</span><span class="p">:</span> <span class="s">"dev_a3f9c12b"</span><span class="p">,</span> <span class="n">"session_id"</span><span class="p">:</span> <span class="s">"sess_7e2f1a"</span><span class="p">,</span>
  <span class="n">"title"</span><span class="p">:</span> <span class="s">""</span><span class="p">,</span> <span class="n">"messages"</span><span class="p">:</span> <span class="p">[],</span> <span class="n">"profile"</span><span class="p">:</span> <span class="s">"default"</span><span class="p">,</span> <span class="n">"workspace"</span><span class="p">:</span> <span class="s">"/path/to/workspace"</span> <span class="p">}</span>
<span class="p">{</span> <span class="n">"type"</span><span class="p">:</span> <span class="s">"chat_list"</span><span class="p">,</span> <span class="n">"chats"</span><span class="p">:</span> <span class="p">[],</span> <span class="n">"profile"</span><span class="p">:</span> <span class="s">"default"</span> <span class="p">}</span>
<span class="p">{</span> <span class="n">"type"</span><span class="p">:</span> <span class="s">"profile_info"</span><span class="p">,</span> <span class="n">"name"</span><span class="p">:</span> <span class="s">"default"</span><span class="p">,</span> <span class="n">"workspace"</span><span class="p">:</span> <span class="s">"/path/to/workspace"</span> <span class="p">}</span></code></pre>

  <h3>On reconnect (existing device)</h3>
  <pre><code><span class="c"># Client opens:</span>
ws://localhost:8000/ws/?device=dev_a3f9c12b

<span class="c"># Server restores session from disk and sends:</span>
<span class="p">{</span> <span class="n">"type"</span><span class="p">:</span> <span class="s">"session_info"</span><span class="p">,</span> <span class="n">"device_id"</span><span class="p">:</span> <span class="s">"dev_a3f9c12b"</span><span class="p">,</span> <span class="n">"session_id"</span><span class="p">:</span> <span class="s">"sess_7e2f1a"</span><span class="p">,</span>
  <span class="n">"title"</span><span class="p">:</span> <span class="s">"Tic Tac Toe Header Edit"</span><span class="p">,</span>
  <span class="n">"messages"</span><span class="p">:</span> <span class="p">[</span>
    <span class="p">{</span> <span class="n">"role"</span><span class="p">:</span> <span class="s">"user"</span><span class="p">,</span>      <span class="n">"text"</span><span class="p">:</span> <span class="s">"add tochi to the header"</span> <span class="p">},</span>
    <span class="p">{</span> <span class="n">"role"</span><span class="p">:</span> <span class="s">"assistant"</span><span class="p">,</span> <span class="n">"text"</span><span class="p">:</span> <span class="s">"Done — I updated the &lt;h1&gt; ..."</span> <span class="p">}</span>
  <span class="p">],</span>
  <span class="n">"profile"</span><span class="p">:</span> <span class="s">"tochi"</span><span class="p">,</span> <span class="n">"workspace"</span><span class="p">:</span> <span class="s">"/profiles/tochi/workspace"</span> <span class="p">}</span>
<span class="p">{</span> <span class="n">"type"</span><span class="p">:</span> <span class="s">"chat_list"</span><span class="p">,</span> <span class="n">"chats"</span><span class="p">:</span> <span class="p">[{</span> <span class="n">"id"</span><span class="p">:</span> <span class="s">"sess_7e2f1a"</span><span class="p">,</span> <span class="n">"title"</span><span class="p">:</span> <span class="s">"Tic Tac Toe Header Edit"</span><span class="p">,</span> <span class="k">...</span> <span class="p">}],</span> <span class="k">...</span> <span class="p">}</span>
<span class="p">{</span> <span class="n">"type"</span><span class="p">:</span> <span class="s">"profile_info"</span><span class="p">,</span> <span class="n">"name"</span><span class="p">:</span> <span class="s">"tochi"</span><span class="p">,</span> <span class="k">...</span> <span class="p">}</span></code></pre>

  <h3>Sending a message</h3>
  <pre><code><span class="c"># Client sends:</span>
<span class="p">{</span> <span class="n">"type"</span><span class="p">:</span> <span class="s">"user_message"</span><span class="p">,</span> <span class="n">"text"</span><span class="p">:</span> <span class="s">"what is 2 + 2?"</span> <span class="p">}</span>

<span class="c"># Server streams back:</span>
<span class="p">{</span> <span class="n">"type"</span><span class="p">:</span> <span class="s">"token"</span><span class="p">,</span> <span class="n">"text"</span><span class="p">:</span> <span class="s">"2"</span> <span class="p">}</span>
<span class="p">{</span> <span class="n">"type"</span><span class="p">:</span> <span class="s">"token"</span><span class="p">,</span> <span class="n">"text"</span><span class="p">:</span> <span class="s">" +"</span> <span class="p">}</span>
<span class="p">{</span> <span class="n">"type"</span><span class="p">:</span> <span class="s">"token"</span><span class="p">,</span> <span class="n">"text"</span><span class="p">:</span> <span class="s">" 2 = 4"</span> <span class="p">}</span>
<span class="p">{</span> <span class="n">"type"</span><span class="p">:</span> <span class="s">"done"</span> <span class="p">}</span>
<span class="c"># On first message of a new chat, also:</span>
<span class="p">{</span> <span class="n">"type"</span><span class="p">:</span> <span class="s">"chat_title"</span><span class="p">,</span> <span class="n">"title"</span><span class="p">:</span> <span class="s">"Simple Math Question"</span><span class="p">,</span> <span class="n">"session_id"</span><span class="p">:</span> <span class="s">"sess_7e2f1a"</span> <span class="p">}</span></code></pre>
</section>

<!-- ═══════════════════════════════════ SERVER EVENTS ═══════════════════════════════════ -->
<section id="ws-server-events">
  <h2>Server → Client Events</h2>
  <p>Every event is a JSON object with a <code>type</code> field. Events are delivered in the order they are produced.</p>

  <h3>Session &amp; identity</h3>
  <table class="event-table">
    <tr><th>type</th><th>Fields</th><th>When sent</th></tr>
    <tr>
      <td class="event-type">session_info</td>
      <td><code>device_id</code>, <code>session_id</code>, <code>title</code>, <code>messages</code> (array of <code>{role,text}</code>), <code>profile</code>, <code>workspace</code></td>
      <td>On every WebSocket connect, after <code>new_chat</code>, after <code>switch_chat</code></td>
    </tr>
    <tr>
      <td class="event-type">chat_list</td>
      <td><code>chats</code> (array), <code>profile</code> — each chat: <code>id</code>, <code>title</code>, <code>created_at</code>, <code>updated_at</code>, <code>message_count</code>, <code>preview</code></td>
      <td>On connect, after session switches, after title generated, after profile switch, after delete</td>
    </tr>
    <tr>
      <td class="event-type">profile_info</td>
      <td><code>name</code>, <code>workspace</code></td>
      <td>On connect and after every profile change</td>
    </tr>
    <tr>
      <td class="event-type">chat_title</td>
      <td><code>title</code>, <code>session_id</code></td>
      <td>After the first message in a new chat — generated in parallel with the AI response</td>
    </tr>
    <tr>
      <td class="event-type">profile_switch_done</td>
      <td><code>name</code></td>
      <td>After a successful profile switch via <code>switch_profile_request</code></td>
    </tr>
    <tr>
      <td class="event-type">reset_done</td>
      <td><code>session_id</code></td>
      <td>After <code>reset</code> message clears the session history</td>
    </tr>
  </table>

  <h3>AI response streaming</h3>
  <table class="event-table">
    <tr><th>type</th><th>Fields</th><th>Notes</th></tr>
    <tr>
      <td class="event-type">token</td>
      <td><code>text</code></td>
      <td>Streaming AI text — concatenate these to build the full response</td>
    </tr>
    <tr>
      <td class="event-type">done</td>
      <td>—</td>
      <td>Signals the end of the AI's response for this turn</td>
    </tr>
    <tr>
      <td class="event-type">error</td>
      <td><code>message</code>, <code>step_id</code> (optional)</td>
      <td>An error occurred — may be mid-workflow or at the top level</td>
    </tr>
    <tr>
      <td class="event-type">compaction</td>
      <td><code>removed</code>, <code>kept</code></td>
      <td>History was compacted to stay within token limits</td>
    </tr>
  </table>

  <h3>Workflow execution</h3>
  <table class="event-table">
    <tr><th>type</th><th>Key fields</th><th>Notes</th></tr>
    <tr><td class="event-type">workflow_start</td><td><code>workflow_id</code>, <code>name</code></td><td>AI invoked <code>workflow_orchestrator</code></td></tr>
    <tr><td class="event-type">step_start</td><td><code>step_id</code>, <code>step_type</code> (sequential/parallel/loop/…)</td><td></td></tr>
    <tr><td class="event-type">tool_call</td><td><code>step_id</code>, <code>tool</code>, <code>args</code></td><td>A tool is about to be called</td></tr>
    <tr><td class="event-type">tool_result</td><td><code>step_id</code>, <code>tool</code>, <code>result</code>, <code>error</code>, <code>duration_ms</code></td><td><code>error</code> is <code>null</code> on success</td></tr>
    <tr><td class="event-type">variable_set</td><td><code>name</code> (e.g. <code>$result</code>), <code>var_type</code>, <code>size_bytes</code>, <code>value_preview</code></td><td></td></tr>
    <tr><td class="event-type">step_done</td><td><code>step_id</code>, <code>duration_ms</code></td><td></td></tr>
    <tr><td class="event-type">workflow_done</td><td><code>workflow_id</code>, <code>variables</code></td><td>All steps finished; variables is a snapshot of the store</td></tr>
    <tr><td class="event-type">condition_eval</td><td><code>step_id</code>, <code>condition</code>, <code>result</code> (bool)</td><td>Conditional / loop branches</td></tr>
    <tr><td class="event-type">loop_iteration</td><td><code>step_id</code>, <code>iteration</code>, <code>max</code></td><td></td></tr>
    <tr><td class="event-type">map_item</td><td><code>step_id</code>, <code>index</code>, <code>total</code></td><td></td></tr>
    <tr><td class="event-type">retry_attempt</td><td><code>step_id</code>, <code>attempt</code>, <code>max</code></td><td></td></tr>
    <tr><td class="event-type">retry_backoff</td><td><code>step_id</code>, <code>delay_seconds</code></td><td></td></tr>
    <tr><td class="event-type">memory_update</td><td><code>key</code>, <code>value</code></td><td>A memory key was persisted</td></tr>
  </table>

  <h3>User approval</h3>
  <table class="event-table">
    <tr><th>type</th><th>Fields</th><th>Notes</th></tr>
    <tr>
      <td class="event-type">approval_required</td>
      <td><code>request_id</code>, <code>tool</code>, <code>args</code>, <code>step_id</code>, <code>message</code></td>
      <td>The workflow is paused. Client must respond with <code>approval_response</code> using the same <code>request_id</code>.</td>
    </tr>
  </table>

  <h3>Background shell processes</h3>
  <table class="event-table">
    <tr><th>type</th><th>Fields</th></tr>
    <tr><td class="event-type">shell_process_start</td><td><code>pid</code>, <code>command</code></td></tr>
    <tr><td class="event-type">shell_output</td><td><code>pid</code>, <code>stream</code> ("stdout"/"stderr"), <code>lines</code> (string array)</td></tr>
    <tr><td class="event-type">shell_process_done</td><td><code>pid</code>, <code>exit_code</code></td></tr>
  </table>

  <h3>Keep-alive</h3>
  <table class="event-table">
    <tr><th>type</th><th>Notes</th></tr>
    <tr><td class="event-type">pong</td><td>Response to a client <code>ping</code></td></tr>
  </table>
</section>

<!-- ═══════════════════════════════════ CLIENT MESSAGES ═══════════════════════════════════ -->
<section id="ws-client-msgs">
  <h2>Client → Server Messages</h2>

  <h3>Chat</h3>
  <pre><code><span class="c">// Send a message to the AI</span>
<span class="p">{</span> <span class="n">"type"</span><span class="p">:</span> <span class="s">"user_message"</span><span class="p">,</span> <span class="n">"text"</span><span class="p">:</span> <span class="s">"open YouTube"</span> <span class="p">}</span></code></pre>

  <h3>Chat management</h3>
  <pre><code><span class="c">// Start a brand-new empty chat</span>
<span class="p">{</span> <span class="n">"type"</span><span class="p">:</span> <span class="s">"new_chat"</span> <span class="p">}</span>

<span class="c">// Switch to an existing saved chat</span>
<span class="p">{</span> <span class="n">"type"</span><span class="p">:</span> <span class="s">"switch_chat"</span><span class="p">,</span> <span class="n">"chat_id"</span><span class="p">:</span> <span class="s">"sess_7e2f1a"</span> <span class="p">}</span>

<span class="c">// Delete a chat (if current chat, a new one is auto-created)</span>
<span class="p">{</span> <span class="n">"type"</span><span class="p">:</span> <span class="s">"delete_chat"</span><span class="p">,</span> <span class="n">"chat_id"</span><span class="p">:</span> <span class="s">"sess_7e2f1a"</span> <span class="p">}</span>

<span class="c">// Clear the current session's history (keeps the session ID)</span>
<span class="p">{</span> <span class="n">"type"</span><span class="p">:</span> <span class="s">"reset"</span> <span class="p">}</span></code></pre>

  <h3>Profile switching</h3>
  <pre><code><span class="c">// Request a profile switch — triggers an approval dialog on the frontend</span>
<span class="p">{</span> <span class="n">"type"</span><span class="p">:</span> <span class="s">"switch_profile_request"</span><span class="p">,</span> <span class="n">"name"</span><span class="p">:</span> <span class="s">"tochi"</span> <span class="p">}</span>
<span class="c">// Server responds with approval_required, then client responds:</span>
<span class="p">{</span> <span class="n">"type"</span><span class="p">:</span> <span class="s">"approval_response"</span><span class="p">,</span> <span class="n">"request_id"</span><span class="p">:</span> <span class="s">"appr_ui_tochi_..."</span><span class="p">,</span> <span class="n">"approved"</span><span class="p">:</span> <span class="nb">true</span> <span class="p">}</span></code></pre>

  <h3>Tool approval</h3>
  <pre><code><span class="c">// Respond to an approval_required event</span>
<span class="p">{</span> <span class="n">"type"</span><span class="p">:</span> <span class="s">"approval_response"</span><span class="p">,</span> <span class="n">"request_id"</span><span class="p">:</span> <span class="s">"appr_step_123"</span><span class="p">,</span> <span class="n">"approved"</span><span class="p">:</span> <span class="nb">true</span> <span class="p">}</span></code></pre>

  <h3>Keep-alive</h3>
  <pre><code><span class="p">{</span> <span class="n">"type"</span><span class="p">:</span> <span class="s">"ping"</span> <span class="p">}</span>
<span class="c">// Server responds: { "type": "pong" }</span></code></pre>
</section>

<!-- ═══════════════════════════════════ REST HEALTH ═══════════════════════════════════ -->
<section id="rest-health">
  <h2>REST — Health</h2>
  <div class="endpoint">
    <div class="endpoint-header">
      <span class="method get">GET</span>
      <span class="endpoint-path">/health</span>
      <span class="endpoint-desc">No auth required</span>
    </div>
    <div class="endpoint-body">
      <p>Returns server status and current model config. Use this to check if the server is up.</p>
      <pre><code><span class="p">{</span> <span class="n">"status"</span><span class="p">:</span> <span class="s">"ok"</span><span class="p">,</span> <span class="n">"provider"</span><span class="p">:</span> <span class="s">"anthropic"</span><span class="p">,</span> <span class="n">"model"</span><span class="p">:</span> <span class="s">"claude-sonnet-4-6"</span> <span class="p">}</span></code></pre>
    </div>
  </div>
</section>

<!-- ═══════════════════════════════════ REST PROFILES ═══════════════════════════════════ -->
<section id="rest-profiles">
  <h2>REST — Profiles</h2>
  <div class="endpoint">
    <div class="endpoint-header">
      <span class="method get">GET</span>
      <span class="endpoint-path">/api/profiles</span>
    </div>
    <div class="endpoint-body">
      <p>List all profiles on the server.</p>
      <pre><code><span class="p">{</span> <span class="n">"profiles"</span><span class="p">:</span> <span class="p">[</span><span class="s">"default"</span><span class="p">,</span> <span class="s">"tochi"</span><span class="p">,</span> <span class="s">"kachi"</span><span class="p">]</span> <span class="p">}</span></code></pre>
    </div>
  </div>
</section>

<!-- ═══════════════════════════════════ REST CHATS ═══════════════════════════════════ -->
<section id="rest-chats">
  <h2>REST — Chats</h2>
  <div class="endpoint">
    <div class="endpoint-header">
      <span class="method get">GET</span>
      <span class="endpoint-path">/api/profile/{name}/chats</span>
    </div>
    <div class="endpoint-body">
      <p>List all saved chats for a profile, sorted by most recent first.</p>
      <pre><code><span class="p">[</span>
  <span class="p">{</span>
    <span class="n">"id"</span><span class="p">:</span>            <span class="s">"sess_7e2f1a"</span><span class="p">,</span>
    <span class="n">"title"</span><span class="p">:</span>         <span class="s">"Tic Tac Toe Header Edit"</span><span class="p">,</span>
    <span class="n">"created_at"</span><span class="p">:</span>    <span class="nb">1713200400.0</span><span class="p">,</span>   <span class="c">// Unix timestamp</span>
    <span class="n">"updated_at"</span><span class="p">:</span>    <span class="nb">1713201600.0</span><span class="p">,</span>
    <span class="n">"message_count"</span><span class="p">:</span> <span class="nb">6</span><span class="p">,</span>
    <span class="n">"preview"</span><span class="p">:</span>       <span class="s">"I've updated the &lt;h1&gt; tag to show Tochi..."</span>
  <span class="p">}</span>
<span class="p">]</span></code></pre>
    </div>
  </div>
  <div class="endpoint">
    <div class="endpoint-header">
      <span class="method delete">DELETE</span>
      <span class="endpoint-path">/api/profile/{name}/chats/{chat_id}</span>
    </div>
    <div class="endpoint-body">
      <p>Permanently delete a saved chat. Also removes it from in-memory sessions.</p>
      <pre><code><span class="p">{</span> <span class="n">"deleted"</span><span class="p">:</span> <span class="nb">true</span><span class="p">,</span> <span class="n">"id"</span><span class="p">:</span> <span class="s">"sess_7e2f1a"</span> <span class="p">}</span></code></pre>
    </div>
  </div>
</section>

<!-- ═══════════════════════════════════ REST SESSIONS ═══════════════════════════════════ -->
<section id="rest-sessions">
  <h2>REST — Sessions</h2>
  <div class="endpoint">
    <div class="endpoint-header">
      <span class="method get">GET</span><span class="endpoint-path">/api/sessions</span>
    </div>
    <div class="endpoint-body"><p>List all in-memory active sessions (resets on server restart).</p></div>
  </div>
  <div class="endpoint">
    <div class="endpoint-header">
      <span class="method delete">DELETE</span><span class="endpoint-path">/api/session/{session_id}</span>
    </div>
    <div class="endpoint-body"><p>Evict a session from memory (history on disk is preserved).</p></div>
  </div>
  <div class="endpoint">
    <div class="endpoint-header">
      <span class="method post">POST</span><span class="endpoint-path">/api/session/{session_id}/reset</span>
    </div>
    <div class="endpoint-body"><p>Clear the in-memory history for a session.</p></div>
  </div>
  <div class="endpoint">
    <div class="endpoint-header">
      <span class="method get">GET</span><span class="endpoint-path">/api/session/{session_id}/variables</span>
    </div>
    <div class="endpoint-body"><p>Snapshot of the session's variable store.</p></div>
  </div>
  <div class="endpoint">
    <div class="endpoint-header">
      <span class="method get">GET</span><span class="endpoint-path">/api/session/{session_id}/memory</span>
    </div>
    <div class="endpoint-body"><p>All persisted memory entries for the session's active profile.</p></div>
  </div>
  <div class="endpoint">
    <div class="endpoint-header">
      <span class="method get">GET</span><span class="endpoint-path">/api/session/{session_id}/history</span>
    </div>
    <div class="endpoint-body"><p>Full raw message history (system messages stripped). Useful for debugging.</p></div>
  </div>
</section>

<!-- ═══════════════════════════════════ REST CONFIG ═══════════════════════════════════ -->
<section id="rest-config">
  <h2>REST — Config &amp; Tools</h2>
  <div class="endpoint">
    <div class="endpoint-header">
      <span class="method get">GET</span><span class="endpoint-path">/api/config</span>
    </div>
    <div class="endpoint-body">
      <pre><code><span class="p">{</span>
  <span class="n">"provider"</span><span class="p">:</span>           <span class="s">"anthropic"</span><span class="p">,</span>
  <span class="n">"model"</span><span class="p">:</span>             <span class="s">"claude-sonnet-4-6"</span><span class="p">,</span>
  <span class="n">"max_history_tokens"</span><span class="p">:</span> <span class="nb">32000</span><span class="p">,</span>
  <span class="n">"max_tool_turns"</span><span class="p">:</span>     <span class="nb">10</span><span class="p">,</span>
  <span class="n">"auth_enabled"</span><span class="p">:</span>       <span class="nb">false</span>
<span class="p">}</span></code></pre>
    </div>
  </div>
  <div class="endpoint">
    <div class="endpoint-header">
      <span class="method get">GET</span><span class="endpoint-path">/api/tools</span>
      <span class="endpoint-desc">Lists all registered tools with schemas</span>
    </div>
    <div class="endpoint-body"></div>
  </div>
  <div class="endpoint">
    <div class="endpoint-header">
      <span class="method get">GET</span><span class="endpoint-path">/api/skills</span>
      <span class="endpoint-desc">Lists all loaded skills and their workflow examples</span>
    </div>
    <div class="endpoint-body"></div>
  </div>
</section>

<!-- ═══════════════════════════════════ REST SPOTIFY ═══════════════════════════════════ -->
<section id="rest-spotify">
  <h2>REST — Spotify OAuth</h2>
  <div class="endpoint">
    <div class="endpoint-header">
      <span class="method get">GET</span><span class="endpoint-path">/auth/spotify</span>
      <span class="endpoint-desc">Redirects to Spotify auth page</span>
    </div>
    <div class="endpoint-body"><p>Requires <code>CHIKA_SPOTIFY_CLIENT_ID</code> and <code>CHIKA_SPOTIFY_CLIENT_SECRET</code> in <code>.env</code>.</p></div>
  </div>
  <div class="endpoint">
    <div class="endpoint-header">
      <span class="method get">GET</span><span class="endpoint-path">/auth/spotify/status</span>
    </div>
    <div class="endpoint-body"><p>Returns whether Spotify is authorized. Includes <code>auth_url</code> if not.</p></div>
  </div>
</section>

<!-- ═══════════════════════════════════ PYTHON EXAMPLE ═══════════════════════════════════ -->
<section id="ex-python">
  <h2>Example — Python CLI Client</h2>
  <pre><code><span class="k">import</span> asyncio, json
<span class="k">import</span> websockets

SERVER  <span class="p">=</span> <span class="s">"ws://localhost:8000"</span>
API_KEY <span class="p">=</span> <span class="s">""</span>          <span class="c"># set if CHIKA_API_KEY is configured</span>

<span class="c"># Load saved device_id from disk so session persists across runs</span>
<span class="k">def</span> <span class="n">load_device_id</span>() <span class="p">-></span> str:
    <span class="k">try</span><span class="p">:</span>
        <span class="k">with</span> <span class="nb">open</span>(<span class="s">".chika_device"</span>) <span class="k">as</span> f: <span class="k">return</span> f.read().strip()
    <span class="k">except</span> FileNotFoundError: <span class="k">return</span> <span class="s">""</span>

<span class="k">def</span> <span class="n">save_device_id</span>(did: str):
    <span class="k">with</span> <span class="nb">open</span>(<span class="s">".chika_device"</span>, <span class="s">"w"</span>) <span class="k">as</span> f: f.write(did)

<span class="k">async def</span> <span class="n">chat</span>(message: str):
    device_id <span class="p">=</span> load_device_id()
    params    <span class="p">=</span> <span class="p">[]</span>
    <span class="k">if</span> API_KEY:  params.append(<span class="s">f"token={API_KEY}"</span>)
    <span class="k">if</span> device_id: params.append(<span class="s">f"device={device_id}"</span>)
    url <span class="p">=</span> <span class="s">f"{SERVER}/ws/"</span> <span class="p">+</span> (<span class="s">"?"</span> <span class="p">+</span> <span class="s">"&"</span>.join(params) <span class="k">if</span> params <span class="k">else</span> <span class="s">""</span>)

    <span class="k">async with</span> websockets.connect(url) <span class="k">as</span> ws:
        <span class="c"># Receive initial events until session_info arrives</span>
        <span class="k">while True</span>:
            ev <span class="p">=</span> json.loads(<span class="k">await</span> ws.recv())
            <span class="k">if</span> ev[<span class="s">"type"</span>] <span class="p">==</span> <span class="s">"session_info"</span>:
                save_device_id(ev[<span class="s">"device_id"</span>])
                <span class="k">break</span>   <span class="c"># skip chat_list and profile_info for now</span>

        <span class="c"># Drain remaining init events (chat_list, profile_info)</span>
        <span class="k">await</span> asyncio.sleep(<span class="nb">0.05</span>)

        <span class="c"># Send user message</span>
        <span class="k">await</span> ws.send(json.dumps(<span class="p">{</span><span class="s">"type"</span><span class="p">:</span> <span class="s">"user_message"</span><span class="p">,</span> <span class="s">"text"</span><span class="p">:</span> message<span class="p">}</span>))

        <span class="c"># Stream response</span>
        response <span class="p">=</span> <span class="s">""</span>
        <span class="k">async for</span> raw <span class="k">in</span> ws:
            ev <span class="p">=</span> json.loads(raw)
            <span class="k">if</span> ev[<span class="s">"type"</span>] <span class="p">==</span> <span class="s">"token"</span>:
                print(ev[<span class="s">"text"</span>], end<span class="p">=</span><span class="s">""</span>, flush<span class="p">=</span><span class="nb">True</span>)
                response <span class="p">+=</span> ev[<span class="s">"text"</span>]
            <span class="k">elif</span> ev[<span class="s">"type"</span>] <span class="p">==</span> <span class="s">"approval_required"</span>:
                answer <span class="p">=</span> input(<span class="s">f"\n[Approve '{ev['tool']}'? y/n] "</span>)
                <span class="k">await</span> ws.send(json.dumps(<span class="p">{</span>
                    <span class="s">"type"</span><span class="p">:</span> <span class="s">"approval_response"</span><span class="p">,</span>
                    <span class="s">"request_id"</span><span class="p">:</span> ev[<span class="s">"request_id"</span>]<span class="p">,</span>
                    <span class="s">"approved"</span><span class="p">:</span> answer.strip().lower() <span class="p">==</span> <span class="s">"y"</span><span class="p">,</span>
                <span class="p">}</span>))
            <span class="k">elif</span> ev[<span class="s">"type"</span>] <span class="p">==</span> <span class="s">"done"</span>:
                print()  <span class="c"># newline after stream</span>
                <span class="k">break</span>
            <span class="k">elif</span> ev[<span class="s">"type"</span>] <span class="p">==</span> <span class="s">"error"</span>:
                print(<span class="s">f"\n[Error: {ev['message']}]"</span>)
                <span class="k">break</span>

<span class="k">if</span> __name__ <span class="p">==</span> <span class="s">"__main__"</span>:
    <span class="k">import</span> sys
    asyncio.run(chat(<span class="s">" "</span>.join(sys.argv[<span class="nb">1</span>:])))
</code></pre>
</section>

<!-- ═══════════════════════════════════ JS EXAMPLE ═══════════════════════════════════ -->
<section id="ex-js">
  <h2>Example — JavaScript / Browser Client</h2>
  <pre><code><span class="k">const</span> DEVICE_KEY <span class="p">=</span> <span class="s">"chika_device_id"</span>

<span class="k">function</span> <span class="n">buildUrl</span>(server <span class="p">=</span> <span class="s">`ws://${location.host}`</span>, apiKey <span class="p">=</span> <span class="s">""</span>) {
  <span class="k">const</span> params <span class="p">=</span> <span class="k">new</span> URLSearchParams()
  <span class="k">if</span> (apiKey) params.set(<span class="s">"token"</span>,  apiKey)
  <span class="k">const</span> did <span class="p">=</span> sessionStorage.getItem(DEVICE_KEY)
  <span class="k">if</span> (did)    params.set(<span class="s">"device"</span>, did)
  <span class="k">return</span> <span class="s">`${server}/ws/${params.toString() ? "?" + params : ""}`</span>
}

<span class="k">const</span> ws <span class="p">=</span> <span class="k">new</span> WebSocket(buildUrl())

ws.onmessage <span class="p">=</span> (e) <span class="p">=></span> {
  <span class="k">const</span> ev <span class="p">=</span> JSON.parse(e.data)

  <span class="k">switch</span> (ev.type) {
    <span class="k">case</span> <span class="s">"session_info"</span><span class="p">:</span>
      sessionStorage.setItem(DEVICE_KEY, ev.device_id)  <span class="c">// persist device ID</span>
      renderMessages(ev.messages)
      setTitle(ev.title)
      <span class="k">break</span>
    <span class="k">case</span> <span class="s">"chat_list"</span><span class="p">:</span>
      renderSidebar(ev.chats)
      <span class="k">break</span>
    <span class="k">case</span> <span class="s">"token"</span><span class="p">:</span>
      appendToCurrentMessage(ev.text)
      <span class="k">break</span>
    <span class="k">case</span> <span class="s">"chat_title"</span><span class="p">:</span>
      setTitle(ev.title)
      <span class="k">break</span>
    <span class="k">case</span> <span class="s">"done"</span><span class="p">:</span>
      finaliseMessage()
      <span class="k">break</span>
    <span class="k">case</span> <span class="s">"approval_required"</span><span class="p">:</span>
      showApprovalDialog(ev)   <span class="c">// your UI sends approval_response when user decides</span>
      <span class="k">break</span>
  }
}

<span class="c">// Send a message</span>
ws.send(JSON.stringify(<span class="p">{</span> type<span class="p">:</span> <span class="s">"user_message"</span><span class="p">,</span> text<span class="p">:</span> <span class="s">"what's the weather in Lagos?"</span> <span class="p">}</span>))

<span class="c">// Start a new chat</span>
ws.send(JSON.stringify(<span class="p">{</span> type<span class="p">:</span> <span class="s">"new_chat"</span> <span class="p">}</span>))

<span class="c">// Switch to an existing chat</span>
ws.send(JSON.stringify(<span class="p">{</span> type<span class="p">:</span> <span class="s">"switch_chat"</span><span class="p">,</span> chat_id<span class="p">:</span> <span class="s">"sess_7e2f1a"</span> <span class="p">}</span>))
</code></pre>
</section>

<!-- ═══════════════════════════════════ CURL ═══════════════════════════════════ -->
<section id="ex-curl">
  <h2>Example — cURL</h2>
  <pre><code><span class="c"># Health check</span>
curl http://localhost:8000/health

<span class="c"># List profiles (no auth)</span>
curl http://localhost:8000/api/profiles

<span class="c"># List profiles (with auth)</span>
curl -H "Authorization: Bearer YOUR_KEY" http://localhost:8000/api/profiles

<span class="c"># List chats for a profile</span>
curl -H "Authorization: Bearer YOUR_KEY" \
     http://localhost:8000/api/profile/tochi/chats

<span class="c"># Delete a chat</span>
curl -X DELETE -H "Authorization: Bearer YOUR_KEY" \
     http://localhost:8000/api/profile/tochi/chats/sess_7e2f1a

<span class="c"># Get server config</span>
curl -H "Authorization: Bearer YOUR_KEY" http://localhost:8000/api/config
</code></pre>
</section>

</main>

<script>
  // Highlight active nav item based on scroll position
  const sections = document.querySelectorAll('section[id]')
  const links    = document.querySelectorAll('nav a')

  function setActive() {
    let current = ''
    sections.forEach(s => {
      if (s.getBoundingClientRect().top <= 60) current = s.id
    })
    links.forEach(l => {
      l.classList.toggle('active', l.getAttribute('href') === '#' + current)
    })
  }

  document.getElementById('main').addEventListener('scroll', setActive)
  setActive()
</script>
</body>
</html>
"""
