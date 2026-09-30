/* NoleCareerShield front-end: small progressive enhancements. Every feature also works without it. */
(function () {
  "use strict";
  var meta = document.querySelector('meta[name="csrf"]');
  var CSRF = meta ? meta.getAttribute("content") : "";

  function post(url, data) {
    return fetch(url, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": CSRF },
      body: JSON.stringify(data)
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok) { throw new Error(j.error || (r.status === 429 ? "Slow down a little and try again." : "Something went wrong. Try again.")); }
        return j;
      });
    });
  }

  function autogrow(t) {
    t.style.height = "auto";
    t.style.height = Math.min(t.scrollHeight + 2, 180) + "px";
  }

  // Character counters
  document.querySelectorAll("[data-count]").forEach(function (el) {
    var max = parseInt(el.getAttribute("maxlength") || "0", 10);
    if (!max) return;
    var c = document.createElement("div");
    c.className = "counter";
    el.insertAdjacentElement("afterend", c);
    var u = function () { c.textContent = el.value.length.toLocaleString() + " / " + max.toLocaleString(); };
    el.addEventListener("input", u); u();
  });

  // Copy buttons
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-copy]");
    if (!b || !navigator.clipboard) return;
    navigator.clipboard.writeText(b.getAttribute("data-copy")).then(function () {
      var old = b.textContent; b.textContent = "Copied"; setTimeout(function () { b.textContent = old; }, 1400);
    });
  });

  // Enter sends, Shift+Enter adds a line (chat and messages)
  function enterSends(textarea, form) {
    textarea.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit ? form.requestSubmit() : form.submit(); }
    });
    textarea.addEventListener("input", function () { autogrow(textarea); });
  }

  // ---------- job assistant ----------
  var chat = document.getElementById("chat");
  if (chat) {
    var log = document.getElementById("log"), form = document.getElementById("ask"), q = document.getElementById("q");
    var history = [], busy = false;
    enterSends(q, form);
    function say(role, text, cardsHtml) {
      var d = document.createElement("div");
      d.className = "say " + (role === "user" ? "me" : "bot");
      if (role !== "user") {
        var w = document.createElement("div"); w.className = "who"; w.textContent = "Assistant"; d.appendChild(w);
      }
      var t = document.createElement("div"); t.textContent = text; d.appendChild(t);
      if (cardsHtml) { var c = document.createElement("div"); c.className = "cards"; c.innerHTML = cardsHtml; d.appendChild(c); }
      log.appendChild(d); log.scrollTop = log.scrollHeight; return d;
    }
    function ask(text) {
      text = (text || "").trim();
      if (!text || busy) return;
      busy = true;
      document.getElementById("sugg").style.display = "none";
      say("user", text);
      history.push({ role: "user", text: text });
      var wait = document.createElement("div"); wait.className = "say bot typing"; wait.textContent = "Looking through the board…";
      log.appendChild(wait); log.scrollTop = log.scrollHeight;
      post(chat.getAttribute("data-api"), { history: history.slice(-16) }).then(function (j) {
        wait.remove();
        say("assistant", j.reply, j.cards_html);
        history.push({ role: "assistant", text: j.reply });
      }).catch(function (err) {
        wait.remove(); say("assistant", err.message); history.pop();
      }).finally(function () { busy = false; q.focus(); });
    }
    form.addEventListener("submit", function (e) { e.preventDefault(); var t = q.value; q.value = ""; autogrow(q); ask(t); });
    chat.querySelectorAll("[data-ask]").forEach(function (b) { b.addEventListener("click", function () { ask(b.getAttribute("data-ask")); }); });
  }

  // ---------- messages ----------
  var thread = document.getElementById("thread");
  if (thread) {
    var cid = thread.getAttribute("data-cid");
    var last = parseInt(thread.getAttribute("data-last") || "0", 10);
    thread.scrollTop = thread.scrollHeight;
    var sendForm = document.querySelector("form[data-send]");
    function append(html, id) {
      if (id && thread.querySelector('[data-id="' + id + '"]')) return;
      var tmp = document.createElement("div"); tmp.innerHTML = html;
      while (tmp.firstChild) thread.appendChild(tmp.firstChild);
      if (id > last) last = id;
      thread.scrollTop = thread.scrollHeight;
    }
    if (sendForm) {
      var box = sendForm.querySelector("textarea");
      enterSends(box, sendForm);
      sendForm.addEventListener("submit", function (e) {
        e.preventDefault();
        var body = box.value.trim(); if (!body) return;
        var btn = sendForm.querySelector("button"); btn.disabled = true;
        post("/api/messages/" + cid, { body: body }).then(function (j) {
          box.value = ""; autogrow(box); append(j.html, j.message.id);
        }).catch(function (err) {
          var n = document.createElement("div"); n.className = "scanbox"; n.textContent = err.message; thread.appendChild(n);
        }).finally(function () { btn.disabled = false; box.focus(); });
      });
    }
    function poll() {
      if (document.hidden) return;
      fetch("/api/messages/" + cid + "?after=" + last, { credentials: "same-origin" }).then(function (r) { return r.ok ? r.json() : null; })
        .then(function (j) { if (j && j.messages) j.messages.forEach(function (m) { append(m.html, m.id); }); })
        .catch(function () {});
    }
    setInterval(poll, 8000);
    document.addEventListener("visibilitychange", poll);
  }

  // ---------- resume: improve a bullet ----------
  var bf = document.querySelector("form[data-bullet]");
  if (bf) {
    bf.addEventListener("submit", function (e) {
      e.preventDefault();
      var out = document.getElementById("bullet-out"), btn = bf.querySelector("button");
      btn.disabled = true; out.innerHTML = '<p class="typing" style="margin-top:10px">Rewriting…</p>';
      post("/api/resume/bullet", { bullet: bf.querySelector("textarea").value }).then(function (j) { out.innerHTML = j.html; })
        .catch(function (err) { out.textContent = err.message; })
        .finally(function () { btn.disabled = false; });
    });
  }
})();
