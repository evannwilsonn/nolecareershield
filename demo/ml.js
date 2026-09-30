/* The learned layer in the browser: the same maths as scam_detector/ml.py, from the same scam_model.json.
 * tests/test_ml_js.py checks that both give the same probability on every holdout listing.
 *
 *   const model = NCSModel.create(spec, NCS.normalize);   // spec = scam_model.json, NCS = demo/engine.js
 *   const f = model.secondLook(title, description, company, url, scored.findings, scored.score);
 *   if (f && (band === "clear" || band === "caution")) { findings.push(f); level = Math.max(level, 1); }
 */
(function (root) {
  "use strict";
  const PLACEHOLDER = /\[[^\]\n]{0,40}\]|\([^)\n]{0,40}redacted[^)\n]{0,40}\)|\bredacted\b/gi;
  const HEADER = /^[ \t>]*(?:from|to|cc|sent|date|subject)[ \t]*:/gim;
  const SCHEME = /https?:\/\/|www\./gi;

  function create(spec, normalize) {
    if (spec.format !== 1) throw new Error("unknown model format " + spec.format);
    const clean = t => (t || "").replace(PLACEHOLDER, " ").replace(HEADER, " ").replace(SCHEME, " ");
    const tokens = t => normalize(clean(t)).toLowerCase().replace(/[0-9]/g, "0").match(/\$?[a-z0-9]+/g) || [];
    const analyzer = t => { const w = tokens(t); return w.concat(w.slice(1).map((b, i) => w[i] + " " + b)); };
    const postingText = (title, description, company, url) => [title, company, description, url].filter(Boolean).join("\n");

    function contributions(title, description, company, url, findings, score) {
      const counts = new Map();
      for (const term of analyzer(postingText(title, description, company, url)))
        if (Object.prototype.hasOwnProperty.call(spec.vocab, term)) counts.set(term, (counts.get(term) || 0) + 1);
      const vals = [...counts].map(([t, c]) => [t, (1 + Math.log(c)) * spec.vocab[t][0]]);
      const norm = Math.sqrt(vals.reduce((s, [, v]) => s + v * v, 0)) || 1;
      const parts = vals.map(([t, v]) => ["phrase", t, v / norm * spec.vocab[t][1]]);
      const fired = new Set((findings || []).map(f => f.rule_id));
      const rf = spec.rule_ids.map(id => fired.has(id) ? 1 : 0).concat([Math.min(100, score || 0) / 100]);
      const names = spec.rule_ids.concat(["rule score"]);
      rf.forEach((x, i) => { if (x) parts.push(["rule", names[i], x * spec.rule_scale * spec.rule_coef[i]]); });
      return [spec.intercept + parts.reduce((s, p) => s + p[2], 0), parts];
    }

    function predict(title, description, company, url, findings, score) {
      const [logit, parts] = contributions(title, description, company, url, findings, score);
      const p = 1 / (1 + Math.exp(-Math.max(-40, Math.min(40, logit))));
      const because = parts.filter(x => x[2] > 0).sort((a, b) => b[2] - a[2]).slice(0, 5)
        .map(([kind, name, w]) => ({kind, name, weight: Math.round(w * 1000) / 1000}));
      return {probability: Math.round(p * 10000) / 10000, flag: p >= spec.threshold, threshold: spec.threshold, version: spec.version, because};
    }

    function secondLook(title, description, company, url, findings, score) {
      const pred = predict(title, description, company, url, findings, score);
      if (!pred.flag) return null;
      const titles = {}; (findings || []).forEach(f => { titles[f.rule_id] = f.title; });
      const reasons = pred.because.filter(b => b.name !== "rule score")
        .map(b => b.kind === "rule" ? (titles[b.name] || b.name.replace(/_/g, " ")) : `"${b.name}"`);
      const n = (spec.trained_on || {}).rows;
      return {rule_id: "model_second_look", severity: "warning", weight: 0, title: "Worth a second look",
        why: `No single rule is sure, but ${n ? `a model trained on ${n} labeled listings` : "the trained model"} rates this ` +
             `${Math.round(pred.probability * 100)}% likely to be a scam. It can send something to a person or suggest caution; it never rejects anything on its own.`,
        matched: reasons.slice(0, 4), model: {probability: pred.probability, version: pred.version}};
    }
    return {predict, secondLook, threshold: spec.threshold, version: spec.version};
  }

  const api = {create};
  root.NCSModel = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
