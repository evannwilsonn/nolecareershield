/* NoleCareerShield visual effects. Decoration only: every page works and reads the same without it.
 *   0. Listing scanner: section[data-scan] runs a gold line down a sample listing and lights each flag.
 *   1. Scroll-scrubbed footage: section[data-cine] pins while you scroll and plays a camera move frame by
 *      frame on a canvas (Apple-style image sequence). Sets --p (0 to 1) and data-cap for the captions.
 *   2. Cursor parallax: [data-pan] layers drift a few pixels against the pointer (fine pointers only).
 *   3. Floating header: over the footage the header is clear; it turns solid once you scroll past.
 *   4. Border light: sets --mx/--my on the card under the cursor so CSS can light its border there.
 *   5. Signed-in pages: score rings, bars and funnels draw in when seen, numbers count up once,
 *      "/" focuses the page's search box, and J/K move between cards in the reviewer queues.
 * Honours prefers-reduced-motion and Save-Data (the footage stays a still photo). Works on pages that
 * re-render in place (the demo): new sections are picked up as they appear, old ones are dropped. */
(function () {
  "use strict";
  if (window.__ncsFx) return;
  window.__ncsFx = true;

  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
  var fine = window.matchMedia("(hover: hover) and (pointer: fine)");
  var conn = navigator.connection || {};
  var lite = !!conn.saveData || /(^|-)2g$/.test(conn.effectiveType || "");
  var SPOT = ".spot,.card,.tile,.job,.hb,.rev-card,.post";
  var root = document.documentElement;

  // ---------- border light ----------
  var spotEl = null, spotX = 0, spotY = 0, spotQueued = false;
  function paintSpot() {
    spotQueued = false;
    if (!spotEl) return;
    var r = spotEl.getBoundingClientRect();
    spotEl.style.setProperty("--mx", (spotX - r.left).toFixed(0) + "px");
    spotEl.style.setProperty("--my", (spotY - r.top).toFixed(0) + "px");
  }
  document.addEventListener("pointermove", function (e) {
    if (!fine.matches || e.pointerType !== "mouse") return;
    var t = e.target && e.target.closest ? e.target.closest(SPOT) : null;
    spotEl = t; spotX = e.clientX; spotY = e.clientY;
    if (t && !spotQueued) { spotQueued = true; requestAnimationFrame(paintSpot); }
  }, { passive: true });

  // ---------- scroll-scrubbed footage ----------
  var cines = [];

  function Cine(sec) {
    var canvas = sec.querySelector("canvas"), ctx = canvas.getContext("2d");
    var n = +sec.getAttribute("data-count") || 0, pat = sec.getAttribute("data-frames") || "";
    var list = window.NCS_FRAMES && window.NCS_FRAMES.length === n ? window.NCS_FRAMES : null;
    var imgs = new Array(n), ok = new Array(n), shown = -1, cur = 0, target = 0, cw = 0, ch = 0;
    var self = { sec: sec, tick: tick, measure: measure };

    function url(i) { return list ? list[i] : pat.replace("{n}", ("00" + i).slice(-3)); }
    function load(i) {
      if (imgs[i]) return;
      var im = new Image(); imgs[i] = im; im.decoding = "async";
      im.onload = function () {
        ok[i] = true;
        var f = Math.round(cur);
        if (shown < 0) draw(f, true);
        else if (Math.abs(i - f) < Math.abs(shown - f)) draw(f);    // a closer frame just arrived
      };
      im.src = url(i);
    }
    // Coarse to fine, so a fast scroll always has a frame close by: 0, every 16th, 8th, 4th, 2nd, the rest.
    var order = [], seen = {};
    [16, 8, 4, 2, 1].forEach(function (step) { for (var i = 0; i < n; i += step) if (!seen[i]) { seen[i] = 1; order.push(i); } });
    if (order.indexOf(n - 1) < 0) order.splice(1, 0, n - 1);
    var next = 0;
    function pump() { for (var k = 0; k < 6 && next < order.length; k++) load(order[next++]); if (next < order.length) setTimeout(pump, 60); }

    function nearest(f) {
      for (var d = 0; d < n; d++) { if (ok[f - d]) return f - d; if (ok[f + d]) return f + d; }
      return -1;
    }
    function measure() {
      var r = canvas.getBoundingClientRect(), dpr = Math.min(window.devicePixelRatio || 1, 2);
      cw = Math.max(1, Math.round(r.width * dpr)); ch = Math.max(1, Math.round(r.height * dpr));
      if (canvas.width !== cw || canvas.height !== ch) {
        canvas.width = cw; canvas.height = ch;
        if (shown >= 0) { var s = shown; shown = -1; draw(s, true); }   // resizing clears the canvas
      }
    }
    function draw(f, force) {
      var i = nearest(f);
      if (i < 0 || (i === shown && !force)) return;
      var im = imgs[i], iw = im.naturalWidth, ih = im.naturalHeight;
      var s = Math.max(cw / iw, ch / ih), w = iw * s, h = ih * s;
      var fx = 0.62;                                     // keep the arch in frame on narrow screens
      var x = Math.min(0, Math.max(cw - w, cw * 0.5 - w * fx)), y = (ch - h) / 2;
      ctx.drawImage(im, x, y, w, h);
      if (shown < 0) sec.classList.add("ready");
      shown = i;
    }
    function tick() {
      var r = sec.getBoundingClientRect(), total = sec.offsetHeight - window.innerHeight;
      var p = total > 0 ? Math.min(1, Math.max(0, -r.top / total)) : 0;
      sec.style.setProperty("--p", p.toFixed(4));
      var cap = p < 0.2 ? "0" : p < 0.62 ? "1" : "2";
      if (sec.getAttribute("data-cap") !== cap) sec.setAttribute("data-cap", cap);
      target = Math.min(1, p / 0.94) * (n - 1);          // the last frame holds for the end of the pin
      cur += (target - cur) * 0.22;
      if (Math.abs(target - cur) < 0.05) cur = target;
      draw(Math.round(cur));
      return Math.abs(target - cur) > 0.05;
    }

    sec.classList.add("live"); sec.setAttribute("data-cap", "0");
    measure(); load(0); load(n - 1);
    if (document.readyState === "complete") pump(); else window.addEventListener("load", pump);
    return self;
  }

  // ---------- listing scanner ----------
  // A gold line runs down the sample listing; each flag lights up as the line passes it, then the stamp
  // lands. On wide screens it follows the scroll (the section pins); on phones it plays once when seen.
  var scans = [];

  function Scan(sec) {
    var card = sec.querySelector(".scan-card"), line = sec.querySelector(".scan-line"), stick = sec.querySelector(".scan-stick");
    var marks = [].slice.call(card.querySelectorAll("mark")), sups = [].slice.call(card.querySelectorAll("sup"));
    var items = {}, h = 1, done = false;
    [].slice.call(sec.querySelectorAll(".scan-flags li")).forEach(function (li) { items[li.getAttribute("data-f")] = li; });
    var verdict = sec.querySelector(".scan-verdict"), stamp = sec.querySelector(".scan-stamp");
    var pinned = window.innerWidth >= 901 && stick.offsetHeight <= window.innerHeight;
    var self = { sec: sec, tick: function () { return false; }, measure: measure };

    function measure() {
      var top = card.getBoundingClientRect().top;
      h = card.offsetHeight;
      marks.forEach(function (m) { m.__y = m.getBoundingClientRect().bottom - top; });
      sups.forEach(function (x) { x.__y = x.getBoundingClientRect().bottom - top; });
    }
    function at(q) {
      var y = Math.max(0, Math.min(1, q)) * h;
      line.style.transform = "translateY(" + y.toFixed(1) + "px)";
      marks.forEach(function (m) {
        var on = m.__y <= y + 3;
        if (on && !m.classList.contains("on")) {
          m.classList.add("on", "flash");
          setTimeout(function () { m.classList.remove("flash"); }, 650);
        } else if (!on) m.classList.remove("on");
      });
      sups.forEach(function (x) {
        var on = x.__y <= y + 3, li = items[x.getAttribute("data-f")];
        x.classList.toggle("on", on);
        if (li) li.classList.toggle("on", on);
      });
    }
    function finish(on) {
      if (on === done) return;
      done = on;
      stamp.classList.toggle("on", on); verdict.classList.toggle("on", on); sec.classList.toggle("done", on);
    }

    sec.classList.add("armed");
    if (pinned) {
      sec.classList.add("pinned");
      self.tick = function () {
        var r = sec.getBoundingClientRect(), total = sec.offsetHeight - window.innerHeight;
        var p = total > 0 ? Math.min(1, Math.max(0, -r.top / total)) : 0;
        at((p - 0.06) / 0.62);
        finish(p > 0.74);
        return false;
      };
    } else {
      // Plays once, the first time most of the card is on screen.
      var io = new IntersectionObserver(function (es) {
        if (!es[0].isIntersecting) return;
        io.disconnect();
        var t0 = performance.now(), D = 2800;
        (function step(now) {
          var q = (now - t0) / D;
          at(q);
          if (q < 1) requestAnimationFrame(step); else setTimeout(function () { finish(true); }, 250);
        })(t0);
      }, { threshold: 0.6 });
      io.observe(card);
    }
    measure(); at(0);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(function () { measure(); kick(); });
    return self;
  }

  // ---------- cursor parallax ----------
  var pans = [], px = 0, py = 0, tx = 0, ty = 0;
  document.addEventListener("pointermove", function (e) {
    if (!pans.length || !fine.matches || reduce.matches) return;
    tx = (e.clientX / window.innerWidth - 0.5) * 2; ty = (e.clientY / window.innerHeight - 0.5) * 2;
    kick();
  }, { passive: true });
  function panStep() {
    px += (tx - px) * 0.08; py += (ty - py) * 0.08;
    var moving = Math.abs(tx - px) > 0.002 || Math.abs(ty - py) > 0.002;
    var t = "translate3d(" + (-px * 14).toFixed(2) + "px," + (-py * 9).toFixed(2) + "px,0)";
    for (var i = 0; i < pans.length; i++) pans[i].style.transform = t;
    return moving;
  }

  // ---------- floating header ----------
  var header = document.querySelector("header"), lead = null;
  function headerStep() {
    if (!header) return;
    var solid = !lead || lead.getBoundingClientRect().bottom < header.offsetHeight + 8;
    header.classList.toggle("solid", solid);
  }

  // ---------- signed-in pages: draw-ins and count-ups ----------
  // Rings, bars, funnels and checklists get .in when they reach the screen (CSS does the drawing);
  // numbers count up once. html.fx arms it all; under reduced motion it is never set, so nothing moves.
  if (!reduce.matches) root.classList.add("fx");
  var DRAW = ".ring,.fitb,.meter,.funnel,.risk,.checklist";
  var COUNT = ".kpi .n,.stat .n,.tile .big,.ring b,.qtabs .n,.pstep .n";
  var seenIO = "IntersectionObserver" in window && !reduce.matches ? new IntersectionObserver(function (es) {
    es.forEach(function (e) {
      if (!e.isIntersecting) return;
      seenIO.unobserve(e.target);
      if (e.target.__count) countUp(e.target); else e.target.classList.add("in");
    });
  }, { rootMargin: "0px 0px -8% 0px" }) : null;
  function countUp(el) {
    var to = el.__count, t0 = performance.now(), D = to > 20 ? 1000 : 650;
    (function step(now) {
      var q = Math.min(1, (now - t0) / D), e = 1 - Math.pow(1 - q, 3);
      el.textContent = String(Math.round(to * e));
      if (q < 1) requestAnimationFrame(step); else el.textContent = el.__text;
    })(t0);
  }
  function arm() {
    document.querySelectorAll(DRAW).forEach(function (el) {
      if (el.__drawn) return; el.__drawn = true;
      if (seenIO) seenIO.observe(el); else el.classList.add("in");
    });
    document.querySelectorAll(COUNT).forEach(function (el) {
      if (el.__counted) return; el.__counted = true;
      var t = el.textContent.trim();
      if (!seenIO || !/^\d{1,5}$/.test(t) || +t === 0) return;
      el.__text = t; el.__count = +t; el.textContent = "0";
      seenIO.observe(el);
    });
  }

  // ---------- keyboard: "/" jumps to search; J and K walk the reviewer's cards ----------
  document.addEventListener("keydown", function (e) {
    if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey) return;
    var t = e.target, typing = t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable);
    if (typing) return;
    if (e.key === "/") {
      var box = document.querySelector('main input[type="search"], main input[name="search"], main input[name="q"]');
      if (box) { e.preventDefault(); box.focus(); box.select(); }
      return;
    }
    if ((e.key === "j" || e.key === "k") && document.querySelector(".desk")) {
      var cards = [].slice.call(document.querySelectorAll("main .rev-card"));
      if (!cards.length) return;
      var i = cards.indexOf(document.querySelector("main .rev-card.cur"));
      i = e.key === "j" ? Math.min(cards.length - 1, i + 1) : Math.max(0, i < 0 ? 0 : i - 1);
      cards.forEach(function (c) { c.classList.remove("cur"); });
      var c = cards[i];
      c.classList.add("cur"); c.setAttribute("tabindex", "-1");
      c.focus({ preventScroll: true });
      c.scrollIntoView({ block: "start", behavior: reduce.matches ? "auto" : "smooth" });
    }
  });

  // ---------- one frame loop for all of it ----------
  var raf = 0;
  function frame() {
    raf = 0;
    var again = false;
    for (var i = 0; i < cines.length; i++) if (cines[i].tick()) again = true;
    for (var j = 0; j < scans.length; j++) scans[j].tick();
    if (pans.length && panStep()) again = true;
    headerStep();
    if (again) raf = requestAnimationFrame(frame);
  }
  function kick() { if (!raf) raf = requestAnimationFrame(frame); }
  window.addEventListener("scroll", kick, { passive: true });
  window.addEventListener("resize", function () {
    for (var i = 0; i < cines.length; i++) cines[i].measure();
    for (var j = 0; j < scans.length; j++) scans[j].measure();
    if (header) root.style.setProperty("--hdr", header.offsetHeight + "px");
    kick();
  });

  function scan() {
    cines = cines.filter(function (c) { return c.sec.isConnected; });
    scans = scans.filter(function (c) { return c.sec.isConnected; });
    pans = Array.prototype.filter.call(document.querySelectorAll("[data-pan]"), function (el) { return el.isConnected; });
    document.querySelectorAll("section[data-cine]").forEach(function (sec) {
      if (sec.__cine) return; sec.__cine = true;
      if (reduce.matches || lite || !("IntersectionObserver" in window)) return;   // stays a still photo
      try { cines.push(Cine(sec)); } catch (e) { /* decoration only */ }
    });
    document.querySelectorAll("section[data-scan]").forEach(function (sec) {
      if (sec.__scan) return; sec.__scan = true;
      if (reduce.matches || !("IntersectionObserver" in window)) return;             // stays finished
      try { scans.push(Scan(sec)); } catch (e) { /* decoration only */ }
    });
    arm();
    var first = document.querySelector("main > .cine:first-child, main > .chapter.top:first-child");
    lead = first;
    header = document.querySelector("header");
    if (header) root.style.setProperty("--hdr", header.offsetHeight + "px");
    root.classList.toggle("over", !!first);
    kick();
  }
  function start() {
    scan();
    // Pages that re-render in place (the demo) get new sections picked up as they appear.
    var queued = false;
    new MutationObserver(function (ms) {
      for (var i = 0; i < ms.length; i++) if (ms[i].addedNodes.length) {
        if (!queued) { queued = true; requestAnimationFrame(function () { queued = false; scan(); }); }
        return;
      }
    }).observe(document.body, { childList: true, subtree: true });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
