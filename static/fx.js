/* NoleCareerShield visual effects. Decoration only: every page works and reads the same without it.
 *   1. Scroll-scrubbed footage: section[data-cine] pins while you scroll and plays a camera move frame by
 *      frame on a canvas (Apple-style image sequence). Sets --p (0 to 1) and data-cap for the captions.
 *   2. Cursor parallax: [data-pan] layers drift a few pixels against the pointer (fine pointers only).
 *   3. Floating header: over the footage the header is clear; it turns solid once you scroll past.
 *   4. Border light: sets --mx/--my on the card under the cursor so CSS can light its border there.
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

  // ---------- one frame loop for all of it ----------
  var raf = 0;
  function frame() {
    raf = 0;
    var again = false;
    for (var i = 0; i < cines.length; i++) if (cines[i].tick()) again = true;
    if (pans.length && panStep()) again = true;
    headerStep();
    if (again) raf = requestAnimationFrame(frame);
  }
  function kick() { if (!raf) raf = requestAnimationFrame(frame); }
  window.addEventListener("scroll", kick, { passive: true });
  window.addEventListener("resize", function () {
    for (var i = 0; i < cines.length; i++) cines[i].measure();
    if (header) root.style.setProperty("--hdr", header.offsetHeight + "px");
    kick();
  });

  function scan() {
    cines = cines.filter(function (c) { return c.sec.isConnected; });
    pans = Array.prototype.filter.call(document.querySelectorAll("[data-pan]"), function (el) { return el.isConnected; });
    document.querySelectorAll("section[data-cine]").forEach(function (sec) {
      if (sec.__cine) return; sec.__cine = true;
      if (reduce.matches || lite || !("IntersectionObserver" in window)) return;   // stays a still photo
      try { cines.push(Cine(sec)); } catch (e) { /* decoration only */ }
    });
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
