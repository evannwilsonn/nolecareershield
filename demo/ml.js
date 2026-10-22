/* The learned layer in the browser: the same maths as scam_detector/ml.py, from the same scam_model.json.
 * tests/test_ml_js.py checks that both give the same probability on every holdout listing.
 * Reads model format 1 (rules + words) and format 2 (rules + words + pieces of words + the shape of the text).
 *
 *   const model = NCSModel.create(spec, NCS.normalize);   // spec = scam_model.json, NCS = demo/engine.js
 *   const f = model.secondLook(title, description, company, url, scored.findings, scored.score);
 *   if (f && (band === "clear" || band === "caution")) { findings.push(f); level = Math.max(level, 1); }
 */
(function (root) {
  "use strict";
  const PLACEHOLDER = /\[[^\]\n]{0,40}\]|\([^)\n]{0,40}redacted[^)\n]{0,40}\)|\bredacted\b|\bperson[0-9]+\b/gi;
  const HEADER = /^[ \t>]*(?:from|to|cc|sent|date|subject)[ \t]*:/gim;
  const SCHEME = /https?:\/\/|www\./gi;
  const CHAR_NGRAMS = [3, 4, 5];

  // Same list and order as ml.SHAPE / ml._RE in scam_detector/ml.py.
  const SHAPE = ["length", "money", "pay_no_amount", "per_period", "urgency", "contact_channel", "email", "free_mail", "url", "shouting",
    "talks_to_you", "talks_as_we", "student", "edu_address", "requirements", "benefits_eeo", "non_ascii", "emoji", "exclamation",
    "digits", "no_experience", "flexible", "tasks", "legal_entity"];
  const SHAPE_TITLES = {length: "short text", money: "money mentions", pay_no_amount: "pay talk with no amount", per_period: "pay per period",
    urgency: "urgency", contact_channel: "personal contact channel", email: "email address in text", free_mail: "free-mail address",
    url: "web addresses", shouting: "SHOUTING", talks_to_you: "written at 'you'", talks_as_we: "speaks as a company",
    student: "aimed at students", edu_address: ".edu address", requirements: "lists requirements", benefits_eeo: "benefits and compliance language",
    non_ascii: "unusual characters", emoji: "emoji", exclamation: "exclamation marks", digits: "many digits",
    no_experience: "no experience needed", flexible: "flexible / work from home", tasks: "tasks and errands", legal_entity: "named legal entity"};
  const RE = {
    money: /\$\s?[0-9][0-9,]*(?:\.[0-9][0-9])?|\b[0-9][0-9,]*\s?(?:dollars|usd)\b/gi,
    payword: /\b(?:pay|paid|salary|wage|stipend|earn|earning|compensation|commission|bonus|allowance)\b/gi,
    per: /\b(?:per|a|each|every)\s+(?:hour|hr|week|month|year|day|task|survey)\b|\b(?:hourly|weekly|monthly|daily|biweekly)\b/gi,
    urgent: /\b(?:urgent|urgently|immediately|asap|right away|today|now|limited|hurry|quick|fast|instant)\b/gi,
    contact: /\b(?:whatsapp|telegram|text me|text us|signal|wechat|dm me|email me|contact me|reach me|reply with|send your|cell|mobile)\b|\+?[0-9]{3}[-. )][0-9]{3}[-. ][0-9]{4}/gi,
    email: /[A-Za-z0-9._+-]+@[A-Za-z0-9-]+\.[A-Za-z0-9.-]+/gi,
    freemail: /@(?:gmail|yahoo|outlook|hotmail|aol|icloud|proton|protonmail|mail)\./i,
    url: /https?:\/\/|www\.|\b[A-Za-z0-9-]+\.(?:com|net|org|io|co|info|biz|xyz|site|online|app)\b/gi,
    shout: /\b[A-Z]{4,}\b/g,
    you: /\byou(?:r|rs|rself)?\b/gi,
    we: /\b(?:we|our|us|company|organization|team)\b/gi,
    student: /\b(?:student|students|campus|university|college|semester|undergrad|freshman|sophomore)\b/gi,
    edu: /@[A-Za-z0-9.-]+\.edu\b/i,
    req: /\b(?:require|required|requirements|qualification|qualifications|degree|bachelor|experience|years of)\b/gi,
    eeo: /\b(?:equal opportunity|eeo|background check|drug screen|benefits|401k|dental|vision|pto|health insurance)\b/gi,
    nonascii: /[^\x00-\x7f]/gu,       // u: count code points, not UTF-16 halves, like Python
    emoji: /[\u{1F300}-\u{1FAFF}☀-➿]/gu,
    excl: /!/g,
    digit: /[0-9]/g,
    noexp: /\bno (?:prior |previous )?experience\b|\bno experience (?:needed|required|necessary)\b|\banyone can\b/i,
    flex: /\b(?:flexible|at your convenience|own hours|your own schedule|work from home|remote|anywhere|home[- ]based)\b/gi,
    task: /\b(?:task|tasks|survey|surveys|data entry|typing|errand|errands|shopping|personal assistant|virtual assistant)\b/gi,
    legal: /\b(?:llc|inc\.?|corporation|corp\.?|ltd|nonprofit|non-profit|department of|office of)\b/i,
  };
  const clean = t => (t || "").replace(PLACEHOLDER, " ").replace(HEADER, " ").replace(SCHEME, " ");
  const count = (k, s) => (s.match(RE[k]) || []).length;
  const has = (k, s) => RE[k].test(s);

  function shapeFeatures(text) {
    const raw = clean(text);
    const len = [...raw].length;                        // code points, as Python's len()
    const n = Math.max(1, len);
    const words = Math.max(1, raw.split(/\s+/).filter(Boolean).length);
    const money = count("money", raw), pay = count("payword", raw);
    return [
      Math.min(1, Math.log(1 + len) / 10),
      Math.min(1, money / 3),
      pay && !money ? 1 : 0,
      Math.min(1, count("per", raw) / 3),
      Math.min(1, count("urgent", raw) / 3),
      Math.min(1, count("contact", raw) / 3),
      Math.min(1, count("email", raw) / 2),
      has("freemail", raw) ? 1 : 0,
      Math.min(1, count("url", raw) / 3),
      Math.min(1, count("shout", raw) / 5),
      Math.min(1, count("you", raw) / words * 10),
      Math.min(1, count("we", raw) / words * 10),
      Math.min(1, count("student", raw) / 3),
      has("edu", raw) ? 1 : 0,
      Math.min(1, count("req", raw) / 4),
      Math.min(1, count("eeo", raw) / 3),
      Math.min(1, count("nonascii", raw) / n * 20),
      Math.min(1, count("emoji", raw) / 3),
      Math.min(1, count("excl", raw) / 5),
      Math.min(1, count("digit", raw) / n * 10),
      has("noexp", raw) ? 1 : 0,
      Math.min(1, count("flex", raw) / 3),
      Math.min(1, count("task", raw) / 3),
      has("legal", raw) ? 1 : 0,
    ];
  }

  function tfidfParts(terms, vocab, kind) {
    const counts = new Map();
    for (const term of terms)
      if (Object.prototype.hasOwnProperty.call(vocab, term)) counts.set(term, (counts.get(term) || 0) + 1);
    const vals = [...counts].map(([t, c]) => [t, (1 + Math.log(c)) * vocab[t][0]]);
    const norm = Math.sqrt(vals.reduce((s, [, v]) => s + v * v, 0)) || 1;
    return vals.map(([t, v]) => [kind, t, v / norm * vocab[t][1]]);
  }

  function create(spec, normalize) {
    if (spec.format !== 1 && spec.format !== 2) throw new Error("unknown model format " + spec.format);
    const tokens = t => normalize(clean(t)).toLowerCase().replace(/[0-9]/g, "0").match(/\$?[a-z0-9]+/g) || [];
    const analyzer = t => { const w = tokens(t); return w.concat(w.slice(1).map((b, i) => w[i] + " " + b)); };
    const charAnalyzer = t => {
      const out = [];
      for (let w of tokens(t)) { w = " " + w + " "; for (const n of CHAR_NGRAMS) for (let i = 0; i + n <= w.length; i++) out.push(w.slice(i, i + n)); }
      return out;
    };
    const postingText = (title, description, company, url) => [title, company, description, url].filter(Boolean).join("\n");
    const cvocab = spec.cvocab || {}, shapeCoef = spec.shape_coef || [], shapeScale = spec.shape_scale || 1;

    function contributions(title, description, company, url, findings, score) {
      const text = postingText(title, description, company, url);
      let parts = tfidfParts(analyzer(text), spec.vocab, "phrase");
      if (spec.format >= 2) {
        parts = parts.concat(tfidfParts(charAnalyzer(text), cvocab, "piece"));
        shapeFeatures(text).forEach((x, i) => { if (x && i < shapeCoef.length) parts.push(["trait", SHAPE[i], x * shapeScale * shapeCoef[i]]); });
      }
      const fired = new Set((findings || []).map(f => f.rule_id));
      const rf = spec.rule_ids.map(id => fired.has(id) ? 1 : 0).concat([Math.min(100, score || 0) / 100]);
      const names = spec.rule_ids.concat(["rule score"]);
      rf.forEach((x, i) => { if (x) parts.push(["rule", names[i], x * spec.rule_scale * spec.rule_coef[i]]); });
      return [spec.intercept + parts.reduce((s, p) => s + p[2], 0), parts];
    }

    function predict(title, description, company, url, findings, score) {
      const [logit, parts] = contributions(title, description, company, url, findings, score);
      const p = 1 / (1 + Math.exp(-Math.max(-40, Math.min(40, logit))));
      const rolled = new Map();
      let pieces = 0;
      for (const [k, n, w] of parts) {
        if (k === "piece") { pieces += w; continue; }
        rolled.set(k + "\u0000" + n, (rolled.get(k + "\u0000" + n) || 0) + w);
      }
      if (pieces > 0) rolled.set("piece\u0000spelling of the words", pieces);
      const because = [...rolled].filter(([, w]) => w > 0).sort((a, b) => b[1] - a[1]).slice(0, 5)
        .map(([key, w]) => { const [kind, name] = key.split("\u0000"); return {kind, name, weight: Math.round(w * 1000) / 1000}; });
      return {probability: Math.round(p * 10000) / 10000, flag: p >= spec.threshold, threshold: spec.threshold, version: spec.version, because};
    }

    function novelty(title, description, company, url) {
      const terms = analyzer(postingText(title, description, company, url));
      if (!terms.length) return 1;
      return Math.round(terms.filter(t => !Object.prototype.hasOwnProperty.call(spec.vocab, t)).length / terms.length * 10000) / 10000;
    }

    function secondLook(title, description, company, url, findings, score) {
      const pred = predict(title, description, company, url, findings, score);
      if (!pred.flag) return null;
      const titles = {}; (findings || []).forEach(f => { titles[f.rule_id] = f.title; });
      const reasons = pred.because.filter(b => b.name !== "rule score")
        .map(b => b.kind === "rule" ? (titles[b.name] || b.name.replace(/_/g, " "))
          : b.kind === "phrase" ? `"${b.name}"`
          : b.kind === "trait" ? (SHAPE_TITLES[b.name] || b.name.replace(/_/g, " ")) : b.name);
      const n = (spec.trained_on || {}).rows;
      return {rule_id: "model_second_look", severity: "warning", weight: 0, title: "Worth a second look",
        why: `No single rule is sure, but ${n ? `a model trained on ${n} labeled listings` : "the trained model"} rates this ` +
             `${Math.round(pred.probability * 100)}% likely to be a scam. It can send something to a person or suggest caution; it never rejects anything on its own.`,
        matched: reasons.slice(0, 4), model: {probability: pred.probability, version: pred.version}};
    }
    return {predict, secondLook, novelty, shapeFeatures, threshold: spec.threshold, version: spec.version, format: spec.format};
  }

  const api = {create, shapeFeatures, SHAPE};
  root.NCSModel = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
