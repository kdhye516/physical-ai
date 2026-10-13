// 맘캠 도우미 챗봇
// 사이트·보고서 내용을 근거로 답하는 RAG 챗봇입니다. (Supabase Edge Function "momcam-chat")
// 페이지에 <script src="chatbot.js" defer></script> 한 줄만 넣으면 오른쪽 아래에 버튼이 생깁니다.
// Gemini API 키는 Supabase 서버에만 있고, 여기에는 공개용 anon 키만 들어 있습니다.
(function () {
  var ENDPOINT = "https://csqbcwbyjckbfgeliamx.supabase.co/functions/v1/momcam-chat";
  var ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNzcWJjd2J5amNrYmZnZWxpYW14Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTE4Mjk2OTgsImV4cCI6MjEwNzQwNTY5OH0.A0GNQBdFOdIqP8RWaLC5sAd_LPHeUR4vhXfb4q3UUSE";
  var STORE = "momcam-chat-history";
  var MAX_LEN = 500;
  var SUGGESTIONS = [
    "맘캠은 어떻게 작동해?",
    "왜 MediaPipe 대신 YOLO-pose를 골랐어?",
    "영상이 클라우드로 전송돼?",
    "인터넷이 끊기면 어떻게 돼?"
  ];

  var CSS = `
    :host { all: initial; }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    .root {
      --ink: #1E2422; --muted: #5E6764; --line: #D5D9D4; --accent: #8FD3F5;
      --bg: #F5F6F3; --surface: #FFFFFF;
      font-family: "Pretendard", -apple-system, "Apple SD Gothic Neo", "Malgun Gothic", sans-serif;
      color: var(--ink); line-height: 1.6; word-break: keep-all;
    }
    .launcher {
      position: fixed; right: 24px; bottom: 24px; z-index: 2147483000;
      display: flex; align-items: center; gap: 8px;
      padding: 14px 20px; border: 0; border-radius: 999px; cursor: pointer;
      background: var(--ink); color: var(--bg);
      font: inherit; font-weight: 600; font-size: 15px;
      box-shadow: 0 8px 24px rgba(30, 36, 34, .25);
    }
    .launcher:hover { background: #000; }
    .launcher:focus-visible, button:focus-visible, textarea:focus-visible, a:focus-visible {
      outline: 3px solid var(--accent); outline-offset: 2px;
    }
    .launcher .dot { width: 10px; height: 10px; border-radius: 50%; background: var(--accent); }

    .panel {
      position: fixed; right: 24px; bottom: 24px; z-index: 2147483001;
      width: 380px; height: min(620px, calc(100vh - 48px));
      display: none; flex-direction: column;
      background: var(--bg); border: 1px solid var(--line); border-radius: 20px;
      box-shadow: 0 16px 48px rgba(30, 36, 34, .22); overflow: hidden;
    }
    .panel.open { display: flex; }
    .head {
      display: flex; align-items: center; justify-content: space-between;
      padding: 16px 18px; background: var(--surface); border-bottom: 1px solid var(--line);
    }
    .head strong { font-size: 16px; font-weight: 800; }
    .head small { display: block; color: var(--muted); font-size: 12px; }
    .icon-btn {
      border: 0; background: transparent; cursor: pointer; color: var(--muted);
      font: inherit; font-size: 13px; padding: 6px 8px; border-radius: 8px;
    }
    .icon-btn:hover { background: var(--bg); color: var(--ink); }
    .close { font-size: 22px; line-height: 1; }

    .log { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 12px; }
    .msg { max-width: 88%; padding: 10px 14px; border-radius: 16px; font-size: 14.5px; overflow-wrap: anywhere; }
    .msg.user { align-self: flex-end; background: var(--ink); color: var(--bg); border-bottom-right-radius: 4px; white-space: pre-wrap; }
    .msg.bot { align-self: flex-start; background: var(--surface); border: 1px solid var(--line); border-bottom-left-radius: 4px; }
    .msg.bot p + p, .msg.bot p + ul, .msg.bot ul + p { margin-top: 8px; }
    .msg.bot ul { padding-left: 18px; }
    .msg.bot li + li { margin-top: 4px; }
    .msg.error { border-color: #E05A4F; color: #9C2F26; }
    .ref { font-size: 11px; font-weight: 700; color: var(--muted); text-decoration: none; vertical-align: super; }
    .ref:hover { color: var(--ink); text-decoration: underline; }
    .sources { margin-top: 10px; padding-top: 8px; border-top: 1px dashed var(--line); font-size: 12.5px; color: var(--muted); }
    .sources a { display: block; color: var(--muted); text-decoration: none; margin-top: 2px; }
    .sources a:hover { color: var(--ink); text-decoration: underline; }

    .typing { display: inline-flex; gap: 4px; }
    .typing span { width: 6px; height: 6px; border-radius: 50%; background: var(--muted); animation: blink 1.2s infinite; }
    .typing span:nth-child(2) { animation-delay: .2s; }
    .typing span:nth-child(3) { animation-delay: .4s; }
    @keyframes blink { 0%, 80%, 100% { opacity: .25; } 40% { opacity: 1; } }

    .chips { display: flex; flex-wrap: wrap; gap: 6px; }
    .chip {
      border: 1px solid var(--line); background: var(--surface); color: var(--ink);
      border-radius: 999px; padding: 6px 12px; font: inherit; font-size: 13px; cursor: pointer;
    }
    .chip:hover { border-color: var(--ink); }

    .form { display: flex; gap: 8px; align-items: flex-end; padding: 12px; background: var(--surface); border-top: 1px solid var(--line); }
    textarea {
      flex: 1; resize: none; max-height: 120px; min-height: 42px;
      padding: 10px 12px; border: 1px solid var(--line); border-radius: 12px;
      font: inherit; font-size: 14.5px; color: var(--ink); background: var(--bg);
    }
    .send {
      height: 42px; padding: 0 16px; border: 0; border-radius: 12px; cursor: pointer;
      background: var(--ink); color: var(--bg); font: inherit; font-weight: 600; font-size: 14px;
    }
    .send:disabled { opacity: .4; cursor: default; }
    .foot { padding: 0 14px 10px; background: var(--surface); font-size: 11px; color: var(--muted); }

    @media (max-width: 480px) {
      .launcher { right: 16px; bottom: 16px; }
      .panel { right: 0; bottom: 0; width: 100vw; height: 100dvh; border-radius: 0; border: 0; }
    }
    @media (prefers-reduced-motion: reduce) { .typing span { animation: none; opacity: .6; } }
  `;

  // ---------- 대화 기록 (탭을 닫으면 사라짐) ----------
  function loadHistory() {
    try { return JSON.parse(sessionStorage.getItem(STORE)) || []; } catch (e) { return []; }
  }
  function saveHistory(h) {
    try { sessionStorage.setItem(STORE, JSON.stringify(h.slice(-20))); } catch (e) { /* 저장 불가 환경은 무시 */ }
  }
  var history = loadHistory(); // [{ role: "user" | "model", text, sources? }]

  // ---------- 화면 만들기 (Shadow DOM으로 사이트 스타일과 분리) ----------
  var host = document.createElement("div");
  host.id = "momcam-chatbot";
  document.body.appendChild(host);
  var shadow = host.attachShadow({ mode: "open" });
  shadow.innerHTML =
    '<style>' + CSS + '</style>' +
    '<div class="root">' +
    '  <button class="launcher" type="button" aria-haspopup="dialog" aria-expanded="false">' +
    '    <span class="dot" aria-hidden="true"></span>맘캠에게 물어보기</button>' +
    '  <section class="panel" role="dialog" aria-label="맘캠 도우미 챗봇">' +
    '    <div class="head">' +
    '      <div><strong>맘캠 도우미</strong><small>사이트와 보고서 내용으로 답해요</small></div>' +
    '      <div><button class="icon-btn reset" type="button">새 대화</button>' +
    '      <button class="icon-btn close" type="button" aria-label="챗봇 닫기">×</button></div>' +
    '    </div>' +
    '    <div class="log" aria-live="polite"></div>' +
    '    <form class="form">' +
    '      <textarea rows="1" maxlength="' + MAX_LEN + '" placeholder="맘캠에 대해 궁금한 점을 물어보세요" aria-label="질문 입력"></textarea>' +
    '      <button class="send" type="submit">보내기</button>' +
    '    </form>' +
    '    <p class="foot">AI 답변은 틀릴 수 있어요. 맘캠은 의료기기가 아닌 보조 모니터링 기기입니다.</p>' +
    '  </section>' +
    '</div>';

  var $ = function (sel) { return shadow.querySelector(sel); };
  var launcher = $(".launcher"), panel = $(".panel"), log = $(".log");
  var form = $(".form"), input = $("textarea"), sendBtn = $(".send");
  var busy = false;

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // 답변의 **굵게**, "- " 목록, [1] 출처 번호만 안전하게 꾸민다 (HTML은 모두 이스케이프)
  function renderAnswer(text, sources) {
    var urlOf = {};
    (sources || []).forEach(function (s) { urlOf[s.n] = s.url; });
    function inline(s) {
      return escapeHtml(s)
        .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
        .replace(/\[(\d+(?:\s*,\s*\d+)*)\]/g, function (m, nums) {
          return nums.split(/\s*,\s*/).map(function (n) {
            return urlOf[n]
              ? '<a class="ref" href="' + escapeHtml(urlOf[n]) + '" target="_top">[' + n + ']</a>'
              : '<span class="ref">[' + n + ']</span>';
          }).join("");
        });
    }
    var html = "", list = false;
    text.split("\n").forEach(function (line) {
      var item = line.match(/^\s*[-*•]\s+(.*)$/);
      if (item) {
        if (!list) { html += "<ul>"; list = true; }
        html += "<li>" + inline(item[1]) + "</li>";
        return;
      }
      if (list) { html += "</ul>"; list = false; }
      if (line.trim()) html += "<p>" + inline(line.trim()) + "</p>";
    });
    if (list) html += "</ul>";
    return html;
  }

  // 답변에서 실제로 인용한 출처만 (같은 주소는 한 번만) 보여 준다
  function renderSources(text, sources) {
    if (!sources || !sources.length) return "";
    var cited = {};
    (text.match(/\[(\d+(?:\s*,\s*\d+)*)\]/g) || []).forEach(function (m) {
      m.replace(/\d+/g, function (n) { cited[n] = true; });
    });
    var seen = {}, links = "";
    sources.forEach(function (s) {
      if (!cited[s.n] || seen[s.url]) return;
      seen[s.url] = true;
      var title = s.title.split(" > ").slice(-1)[0];
      links += '<a href="' + escapeHtml(s.url) + '" target="_top">↗ ' + escapeHtml(title) + "</a>";
    });
    return links ? '<div class="sources">참고한 내용' + links + "</div>" : "";
  }

  function addMessage(role, text, sources, isError) {
    var div = document.createElement("div");
    div.className = "msg " + (role === "user" ? "user" : "bot") + (isError ? " error" : "");
    if (role === "user" || isError) div.textContent = text;
    else div.innerHTML = renderAnswer(text, sources) + renderSources(text, sources);
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
    return div;
  }

  function showWelcome() {
    log.innerHTML = "";
    addMessage("model", "안녕하세요! 맘캠 프로젝트에 대해 궁금한 점을 물어보세요. 작동 방식, 기능, AI 모델, 전처리, 기획 내용까지 사이트와 보고서를 근거로 답해 드려요.");
    var chips = document.createElement("div");
    chips.className = "chips";
    SUGGESTIONS.forEach(function (q) {
      var b = document.createElement("button");
      b.type = "button"; b.className = "chip"; b.textContent = q;
      b.addEventListener("click", function () { ask(q); });
      chips.appendChild(b);
    });
    log.appendChild(chips);
  }

  function restore() {
    if (!history.length) { showWelcome(); return; }
    log.innerHTML = "";
    history.forEach(function (h) { addMessage(h.role, h.text, h.sources); });
  }

  async function ask(question) {
    question = question.trim().slice(0, MAX_LEN);
    if (!question || busy) return;
    busy = true; sendBtn.disabled = true;
    var chips = log.querySelector(".chips");
    if (chips) chips.remove();

    addMessage("user", question);
    var pending = document.createElement("div");
    pending.className = "msg bot";
    pending.setAttribute("aria-label", "답변을 만드는 중");
    pending.innerHTML = '<span class="typing"><span></span><span></span><span></span></span>';
    log.appendChild(pending);
    log.scrollTop = log.scrollHeight;

    var past = history.map(function (h) { return { role: h.role, text: h.text }; });
    try {
      var res = await fetch(ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Authorization": "Bearer " + ANON_KEY, "apikey": ANON_KEY },
        body: JSON.stringify({ message: question, history: past }),
        signal: AbortSignal.timeout(45000) // 45초 안에 답이 없으면 포기
      });
      var data = await res.json().catch(function () { return {}; });
      pending.remove();
      if (!res.ok || data.error) throw new Error(data.error || "잠시 후 다시 시도해 주세요.");
      addMessage("model", data.answer, data.sources);
      history.push({ role: "user", text: question }, { role: "model", text: data.answer, sources: data.sources });
      saveHistory(history);
    } catch (e) {
      pending.remove();
      var msg = e.name === "TimeoutError" ? "답변이 너무 오래 걸려요. 잠시 후 다시 시도해 주세요."
        : e instanceof TypeError ? "연결에 실패했어요. 잠시 후 다시 시도해 주세요."
        : e.message;
      addMessage("model", msg, null, true);
    } finally {
      busy = false; sendBtn.disabled = false;
      input.focus();
    }
  }

  function setOpen(open) {
    panel.classList.toggle("open", open);
    launcher.style.display = open ? "none" : "";
    launcher.setAttribute("aria-expanded", String(open));
    if (open) { if (!log.children.length) restore(); input.focus(); }
    else launcher.focus();
  }

  launcher.addEventListener("click", function () { setOpen(true); });
  $(".close").addEventListener("click", function () { setOpen(false); });
  $(".reset").addEventListener("click", function () { history = []; saveHistory(history); showWelcome(); input.focus(); });
  panel.addEventListener("keydown", function (e) { if (e.key === "Escape") setOpen(false); });

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var q = input.value;
    input.value = ""; input.style.height = "";
    ask(q);
  });
  // Enter로 보내기, Shift+Enter는 줄바꿈 (한글 조합 중에는 보내지 않음)
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); }
  });
  input.addEventListener("input", function () {
    input.style.height = "";
    input.style.height = Math.min(input.scrollHeight, 120) + "px";
  });
})();
