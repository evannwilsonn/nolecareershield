/* NoleCareerShield visual effects. Decoration only: every page works and reads the same without it.
 *   1. Dot grid: canvas[data-fx="grid"] draws a field of dots that lean away from the cursor and
 *      warm to the accent colour near it. Draws only while on screen and moving, then stops.
 *   2. Border light: sets --mx/--my on the card under the cursor so CSS can light its border there.
 * Honours prefers-reduced-motion (the grid is drawn once and never moves). Works on pages that
 * re-render (the demo) because new canvases are picked up as they appear. */
(function () {
  "use strict";
  if (window.__ncsFx) return;
  window.__ncsFx = true;

  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
  var fine = window.matchMedia("(hover: hover) and (pointer: fine)");
  var SPOT = ".spot,.card,.tile,.job,.hero-card,.hb,.rev-card,.post";

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

  // ---------- dot grid ----------
  function cssVar(el, name, fallback) {
    var v = getComputedStyle(el).getPropertyValue(name).trim();
    return v || fallback;
  }
  function toRgb(c) {
    var d = document.createElement("span"); d.style.color = c; document.body.appendChild(d);
    var m = getComputedStyle(d).color.match(/[\d.]+/g) || [0, 0, 0]; d.remove();
    return [+m[0], +m[1], +m[2]];
  }

  function Grid(canvas) {
    var host = canvas.parentElement, ctx = canvas.getContext("2d");
    var dpr = 1, w = 0, h = 0, dots = [], gap = 24, reach = 130;
    var mx = -9999, my = -9999, active = false, visible = false, raf = 0, idle = 0;
    var base = [0, 0, 0], hot = [0, 0, 0];

    function colours() {
      base = toRgb(cssVar(host, "--line-2", "#d9d5c8"));
      hot = toRgb(cssVar(host, "--accent-ink", "#782F40"));
    }
    function layout() {
      var r = host.getBoundingClientRect();
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = Math.max(1, Math.round(r.width)); h = Math.max(1, Math.round(r.height));
      canvas.width = w * dpr; canvas.height = h * dpr;
      gap = w < 640 ? 20 : 24;
      dots = [];
      for (var y = gap / 2; y < h; y += gap) for (var x = gap / 2; x < w; x += gap) dots.push({ x: x, y: y, ox: 0, oy: 0 });
      draw();
    }
    function draw() {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      var moving = false;
      for (var i = 0; i < dots.length; i++) {
        var d = dots[i], dx = d.x - mx, dy = d.y - my, dist = Math.sqrt(dx * dx + dy * dy);
        var k = active && !reduce.matches ? Math.max(0, 1 - dist / reach) : 0;
        var tx = k ? (dx / (dist || 1)) * k * 14 : 0, ty = k ? (dy / (dist || 1)) * k * 14 : 0;
        d.ox += (tx - d.ox) * 0.18; d.oy += (ty - d.oy) * 0.18;
        if (Math.abs(d.ox - tx) > 0.05 || Math.abs(d.oy - ty) > 0.05) moving = true;
        var r0 = base[0] + (hot[0] - base[0]) * k, g0 = base[1] + (hot[1] - base[1]) * k, b0 = base[2] + (hot[2] - base[2]) * k;
        ctx.fillStyle = "rgba(" + (r0 | 0) + "," + (g0 | 0) + "," + (b0 | 0) + "," + (0.55 + 0.45 * k) + ")";
        ctx.beginPath(); ctx.arc(d.x + d.ox, d.y + d.oy, 1.15 + k * 1.3, 0, 6.2832); ctx.fill();
      }
      return moving;
    }
    function loop() {
      raf = 0;
      var moving = draw();
      idle = moving || active ? 0 : idle + 1;
      if (visible && (moving || active) && idle < 2) raf = requestAnimationFrame(loop);
    }
    function kick() { if (!raf && visible && !reduce.matches) raf = requestAnimationFrame(loop); }

    host.addEventListener("pointermove", function (e) {
      var r = host.getBoundingClientRect();
      mx = e.clientX - r.left; my = e.clientY - r.top; active = true; kick();
    }, { passive: true });
    host.addEventListener("pointerleave", function () { active = false; mx = my = -9999; kick(); });

    if ("IntersectionObserver" in window) {
      new IntersectionObserver(function (es) { visible = es[0].isIntersecting; if (visible) kick(); }).observe(host);
    } else visible = true;
    if ("ResizeObserver" in window) new ResizeObserver(function () { layout(); }).observe(host);
    else window.addEventListener("resize", layout);
    var scheme = window.matchMedia("(prefers-color-scheme: dark)");
    var recolour = function () { colours(); draw(); };
    if (scheme.addEventListener) scheme.addEventListener("change", recolour);
    new MutationObserver(recolour).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    colours(); layout();
  }

  function scan(root) {
    (root || document).querySelectorAll('canvas[data-fx="grid"]').forEach(function (c) {
      if (c.__grid) return; c.__grid = true;
      try { Grid(c); } catch (e) { /* decoration only */ }
    });
  }
  function start() {
    scan();
    // Pages that re-render in place (the demo) get new canvases picked up as they appear.
    new MutationObserver(function (ms) {
      for (var i = 0; i < ms.length; i++) if (ms[i].addedNodes.length) { scan(); return; }
    }).observe(document.body, { childList: true, subtree: true });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
