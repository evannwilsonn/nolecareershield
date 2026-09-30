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

  // ---------- career assistant: send without a full reload ----------
  var csLog = document.getElementById("cs-log");
  var csCtx = document.querySelector(".cs-ctxd");
  if (csCtx && window.matchMedia && window.matchMedia("(max-width: 900px)").matches) csCtx.removeAttribute("open");   // phones: panel folds below the chat
  var pend = document.querySelector("[data-cs-pending]");
  if (pend) location.replace(pend.getAttribute("data-cs-pending"));          // the no-JS page refreshes here after a second; JS goes now
  if (document.querySelector(".cs")) {
    var csBusy = false;
    var csThinking = function () {
      var d = document.createElement("div"); d.className = "cs-think"; d.setAttribute("role", "status");
      d.innerHTML = '<span class="dots" aria-hidden="true"><i></i><i></i><i></i></span> Thinking…';
      return d;
    };
    var csSend = function (form) {
      var fd = new FormData(form), q = String(fd.get("q") || "").trim(), cid = String(fd.get("cid") || "");
      if (!q || csBusy) return;
      csBusy = true;
      var input = form.querySelector('input[name="q"]');
      if (input) input.value = "";
      var wait = csThinking(), mine = null;
      if (csLog) {
        document.querySelectorAll(".cs-follow").forEach(function (f) { f.remove(); });
        mine = document.createElement("div"); mine.className = "cs-me"; mine.textContent = q;
        var anchor = document.getElementById("latest");
        csLog.insertBefore(mine, anchor); csLog.insertBefore(wait, anchor);
        wait.scrollIntoView({ block: "end", behavior: "smooth" });
      } else {
        var home = document.querySelector(".cs-home");
        if (home) home.appendChild(wait);
      }
      post("/api/assistant/send", { q: q, cid: cid }).then(function (j) {
        if (!csLog || String(j.cid) !== (csLog.getAttribute("data-cid") || "")) { location.assign(j.url + "#latest"); return; }
        wait.remove(); if (mine) mine.remove();
        var tmp = document.createElement("div"); tmp.innerHTML = j.html;
        var first = tmp.firstElementChild, last = null;
        while (tmp.firstChild) { last = tmp.firstChild; csLog.insertBefore(last, document.getElementById("latest")); }
        var side = document.querySelector(".cs-ctx");
        if (side && j.ctx) {
          var open = csCtx ? csCtx.hasAttribute("open") : true;
          side.outerHTML = j.ctx;
          csCtx = document.querySelector(".cs-ctxd");
          if (csCtx && !open) csCtx.removeAttribute("open");
        }
        if (last && last.scrollIntoView) last.scrollIntoView({ block: "start", behavior: "smooth" });
        else if (first && first.scrollIntoView) first.scrollIntoView({ block: "start" });
      }).catch(function (err) {
        wait.className = "cs-err"; wait.textContent = err.message;
        if (input && !input.value) input.value = q;
      }).finally(function () { csBusy = false; if (input) input.focus(); });
    };
    document.addEventListener("submit", function (e) {
      var f = e.target;
      if (f.hasAttribute && f.hasAttribute("data-cs-ask")) { e.preventDefault(); csSend(f); return; }
      if (f.classList && f.classList.contains("cs-fb")) {             // thumbs: save in place
        e.preventDefault();
        var btn = f.querySelector("button"), acts = f.parentElement;
        fetch(f.action, { method: "POST", body: new FormData(f), credentials: "same-origin" }).then(function (r) {
          if (!r.ok) return;
          var was = btn.classList.contains("on");
          acts.querySelectorAll(".cs-fb button").forEach(function (b) { b.classList.remove("on"); b.setAttribute("aria-pressed", "false"); });
          if (!was) { btn.classList.add("on"); btn.setAttribute("aria-pressed", "true"); }
        }).catch(function () {});
      }
    });
    document.addEventListener("click", function (e) {                  // copy: straight to the clipboard when it's allowed
      var s = e.target.closest ? e.target.closest(".cs-copy > summary") : null;
      if (!s || !navigator.clipboard) return;
      var t = s.parentElement.querySelector("textarea");
      e.preventDefault();
      navigator.clipboard.writeText(t.value).then(function () { s.classList.add("on"); s.setAttribute("title", "Copied"); },
        function () { s.parentElement.setAttribute("open", ""); });
    });
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
