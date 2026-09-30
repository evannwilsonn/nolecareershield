/* The home page scan scene (showcase.py). Without this script, or with reduced motion, the scene shows its finished
   state. With it, the section gets a tall track and a sticky stage, and a scan line moves down the listing as you
   scroll; each flagged phrase lights up when the line passes it, then the verdict lands. */
(function () {
  "use strict";
  var reduce = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
  var queued = false;

  function clamp(v) { return v < 0 ? 0 : v > 1 ? 1 : v; }

  function update() {
    queued = false;
    var s = document.querySelector("[data-scan].live");
    if (!s) return;
    var track = s.querySelector(".scan-track"), card = s.querySelector(".scan-card");
    var r = track.getBoundingClientRect(), vh = window.innerHeight;
    var p = clamp(-r.top / Math.max(1, r.height - vh * 0.8));        // 0 when the track reaches the top, 1 near its end
    var line = clamp((p - 0.04) / 0.72);                                // the line sweeps during most of the track
    var done = p > 0.8;
    card.style.setProperty("--p", line.toFixed(4));
    card.classList.toggle("scanning", line > 0 && line < 1);
    var c = card.getBoundingClientRect(), y = c.top + line * c.height, lit = {};
    s.querySelectorAll("mark[data-s]").forEach(function (m) {
      var b = m.getBoundingClientRect(), on = done || (line > 0 && y >= b.top + b.height / 2);
      m.classList.toggle("on", on);
      if (on) lit[m.getAttribute("data-s")] = true;
    });
    s.querySelectorAll(".scan-flags li[data-s]").forEach(function (li) { li.classList.toggle("on", !!lit[li.getAttribute("data-s")]); });
    s.querySelectorAll(".scan-stamp, .scan-verdict").forEach(function (el) { el.classList.toggle("on", done); });
  }

  function measure() {           // the sticky stage sits just under the header, whose height changes on phones
    var s = document.querySelector("[data-scan]"), h = document.querySelector("header");
    if (s && h) s.style.setProperty("--hdr", (h.offsetHeight + (parseFloat(getComputedStyle(h).top) || 0)) + "px");
  }

  function queue() { if (!queued) { queued = true; window.requestAnimationFrame(update); } }

  function setup() {
    var s = document.querySelector("[data-scan]");
    if (!s || (reduce && reduce.matches)) return;
    s.classList.add("live");
    measure();
    update();
  }

  window.addEventListener("scroll", queue, { passive: true });
  window.addEventListener("resize", function () { measure(); queue(); });
  window.NCSScan = { setup: setup, update: update };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", setup); else setup();
})();
