/*
 * NoleCareerShield engines, ported line for line from the Python so the demo gives the same answers:
 *   detector  scam_detector/rules.py + scorer.py + leadgen.py + enrichment/{compensation,url_flow}.py
 *   check     msgcheck.py (the "Is this a scam?" verdicts)
 *   match     matching.py (skills, query parsing, ranking)
 *   resume    resume_engine.py (review, bullet rewrites, tailoring)
 *   feed      feed.py relevance rules
 *   assistant assistant.py built-in engine
 * The rules themselves come from scam_detector/rulepack/core.json (NCS_RULEPACK), unchanged.
 * tests/test_demo_engine.py runs this file in Node against the Python on the labeled corpora.
 */
(function (root) {
  "use strict";
  const RULEPACK = root.NCS_RULEPACK;

  // ---------------- helpers ----------------
  const reEsc = s => s.replace(/[.*+?^${}()|[\]\\\/\-#&~]/g, "\\$&");
  function allMatches(rx, text) {
    const out = []; rx.lastIndex = 0; let m;
    while ((m = rx.exec(text)) !== null) { out.push(m); if (m[0] === "") rx.lastIndex++; }
    return out;
  }
  const fmt0 = n => Math.round(n).toLocaleString("en-US");
  const fmtG = n => String(Number(n.toPrecision(6)));
  const title = s => s.replace(/\b[a-z]/g, c => c.toUpperCase());

  // ---------------- normalization (rules.py) ----------------
  const ZERO_WIDTH = /[​‌‍⁠﻿­]/g;
  const HOMO = {"а":"a","е":"e","о":"o","р":"p","с":"c","у":"y","х":"x","і":"i","ѕ":"s","ο":"o","α":"a","ρ":"p","’":"'","‘":"'","“":'"',"”":'"'};
  const HOMO_RX = new RegExp("[" + Object.keys(HOMO).join("") + "]", "g");
  const SPACED = /(?<![a-z0-9])(?:[a-z][ .\-_*]){4,}[a-z](?![a-z0-9])/gi;
  const LEET = /(?<=[a-z])[@$0134](?=[a-z])/gi;
  const LEET_MAP = {"@":"a","$":"s","0":"o","1":"i","3":"e","4":"a"};
  const MAX_TEXT = 20000;
  function normalize(text) {
    text = (text || "").normalize("NFKC").replace(ZERO_WIDTH, "").replace(HOMO_RX, c => HOMO[c]);
    text = text.replace(SPACED, m => m.replace(/[ .\-_*]/g, ""));
    text = text.replace(LEET, m => LEET_MAP[m]);
    return text.slice(0, MAX_TEXT);
  }

  // ---------------- guards ----------------
  const NEGATORS = /\b(?:no|never|not|without|zero|nor|neither|free of|isn't|aren't|doesn't|won't|don't|do not|does not|will not|cannot|can't)\b/gi;
  const REQUIRE = /\b(?:must|need to|needs to|have to|required to|you will pay|you pay)\b/i;
  const AFTER = /\b(?:at no (?:cost|charge)|no cost|free of charge|for free|is free|are free|free to you|covered by|paid for by|paid by|we (?:pay|cover)|is waived|are waived)\b/i;
  const POST_HIRE = /\b(?:upon\s+(?:hire|being hired|acceptance|offer)|after\s+(?:you(?:'re| are)\s+|being\s+|an?\s+|your\s+|the\s+)?(?:hired|hire|offer|accepted|acceptance|background check|first)|once\s+(?:you(?:'re| are)\s+)?(?:hired|accepted)|once\s+your\s+background|for\s+(?:payroll|i-?9|tax|w-?4)|i-?9|w-?4|new hires?)\b/i;
  const SENT_BREAK = /[.;:!?\n]/;
  function sentenceBefore(text, start) {
    const parts = text.slice(Math.max(0, start - 160), start).split(SENT_BREAK);
    return parts[parts.length - 1];
  }
  function sentenceAfter(text, end) {
    const seg = text.slice(end, end + 120); const m = SENT_BREAK.exec(seg);
    return m ? seg.slice(0, m.index) : seg;
  }
  function negated(text, m) {
    const before = sentenceBefore(text, m.index).split(/\s+/).filter(Boolean).slice(-14).join(" ");
    let neg = null; for (const n of allMatches(NEGATORS, before)) neg = n;
    if (neg && !REQUIRE.test(before.slice(neg.index + neg[0].length))) return true;
    return AFTER.test(sentenceAfter(text, m.index + m[0].length));
  }
  function postHire(text, m) {
    return POST_HIRE.test(text.slice(Math.max(0, m.index - 120), m.index + m[0].length + 120));
  }
  const GUARDS = {negation: negated, post_hire: postHire};

  // ---------------- rulepack ----------------
  const RULES = RULEPACK.rules.filter(r => (r.status || "active") === "active").map(r => ({
    id: r.id, severity: r.severity, weight: r.weight, title: r.title, why: r.why,
    guards: r.guards || [], min: Math.max(1, r.min_matches || 1), bonus: r.bonus == null ? 3 : r.bonus,
    rx: (r.phrases || []).map(p => new RegExp("\\b" + reEsc(p.toLowerCase()).replace(/ /g, "\\s+") + "\\b", "gi"))
      .concat((r.patterns || []).map(p => new RegExp(p, "gi"))),
  }));

  function runTextRules(text) {
    text = normalize(text);
    const out = [];
    for (const rule of RULES) {
      const seen = new Map();
      for (const rx of rule.rx) for (const m of allMatches(rx, text)) {
        if (rule.guards.some(g => GUARDS[g](text, m))) continue;
        const key = m[0].toLowerCase().replace(/\s+/g, " ").trim();
        if (!seen.has(key)) seen.set(key, key);
      }
      if (seen.size >= rule.min) {
        const weight = rule.weight + Math.min(2 * rule.bonus, rule.bonus * (seen.size - 1));
        const shown = [...seen.keys()].sort().slice(0, 5).map(s => s.slice(0, 90));
        out.push(F(rule.id, rule.severity, weight, rule.title, rule.why, shown));
      }
    }
    return out;
  }
  function F(rule_id, severity, weight, title, why, matched) { return {rule_id, severity, weight, title, why, matched: matched || []}; }

  // ---------------- implied hourly pay ----------------
  const PAY = /\$\s?([\d,]+(?:\.\d+)?)\s*(?:(?:per|a|each|\/)\s*)?(week|weekly|day|daily)\b/i;
  const HOURS_DAYS = /(\d+(?:\.\d+)?)\s*(?:-|to)\s*(\d+(?:\.\d+)?)\s*hrs?\.?\s*(\d+)\s*days?\s*(?:a|per)\s*week/i;
  const HOURS = /(\d+(?:\.\d+)?)\s*(?:-|to)\s*(\d+(?:\.\d+)?)\s*(?:hrs?|hours?)\s*(?:(?:per|a|\/|each)\s*)?(week|weekly|day|daily)?/i;
  function impliedHourly(text) {
    text = normalize(text);
    const pay = PAY.exec(text); if (!pay) return null;
    const amount = parseFloat(pay[1].replace(/,/g, ""));
    const perWeek = amount * (pay[2].toLowerCase().startsWith("d") ? 5 : 1);
    let hours = null, m = HOURS_DAYS.exec(text);
    if (m) hours = parseFloat(m[2]) * parseFloat(m[3]);
    else { m = HOURS.exec(text); if (m) hours = parseFloat(m[2]) * ((m[3] || "").toLowerCase().startsWith("d") ? 5 : 1); }
    if (!hours || hours <= 0) return null;
    const rate = perWeek / hours; if (rate < 60) return null;
    const p = pay[0].trim();
    return F("implied_hourly", "warning", 18, "The pay works out to far above market",
      `${p} for at most about ${fmtG(hours)} hours a week is roughly $${fmt0(rate)}/hour. Real employers do not pay this for casual, no-experience work.`,
      [`${p} / about ${fmtG(hours)} hrs per week`]);
  }

  // ---------------- compensation vs national medians ----------------
  const BLS = {
    data_entry: ["Data Entry Keyers", 37790, ["data entry", "data-entry", "data processor", "typing", "keyer"]],
    admin_assistant: ["Secretaries & Administrative Assistants", 46010, ["administrative assistant", "admin assistant", "secretary", "office assistant", "administrative support", "clerical"]],
    customer_service: ["Customer Service Representatives", 39680, ["customer service", "customer support", "call center", "customer care", "support representative"]],
    shipping_receiving: ["Shipping, Receiving & Inventory Clerks", 40260, ["shipping", "receiving", "warehouse clerk", "package handler", "reshipping", "shipping coordinator", "logistics coordinator"]],
    personal_assistant: ["Personal & Executive Assistants", 46010, ["personal assistant", "executive assistant", "virtual assistant"]],
    bookkeeper: ["Bookkeeping & Accounting Clerks", 47440, ["bookkeeper", "bookkeeping", "accounting clerk", "accounts payable", "accounts receivable", "payment processor", "payment processing"]],
    receptionist: ["Receptionists", 35840, ["receptionist", "front desk"]],
    general_office: ["General Office Clerks", 40480, ["office clerk", "general office", "remote assistant", "work from home assistant", "remote worker"]],
    sales_rep: ["Sales Representatives (non-technical)", 63230, ["sales representative", "sales rep", "account executive", "inside sales"]],
    software_dev: ["Software Developers", 132270, ["software engineer", "software developer", "developer", "programmer", "full stack", "backend engineer", "frontend engineer"]],
    data_analyst: ["Data / Operations Analysts", 83640, ["data analyst", "business analyst", "operations analyst"]],
  };
  const PAYPAT = /\$\s?([\d,]+(?:\.\d+)?)\s*(?:-|–|to|\+)?\s*(?:\$?\s?([\d,]+(?:\.\d+)?))?\s*(?:\/|per|an?\s)?\s*(hour|hr|day|week|month|year|annum|yr)/gi;
  function compensation(ttl, desc) {
    const text = `${ttl}\n${desc}`; const pays = [];
    for (const m of allMatches(PAYPAT, text)) {
      const hi = parseFloat((m[2] || m[1]).replace(/,/g, "")); const u = m[3].toLowerCase();
      pays.push(u === "hour" || u === "hr" ? hi * 2080 : u === "day" ? hi * 260 : u === "week" ? hi * 52 : u === "month" ? hi * 12 : hi);
    }
    if (!pays.length) return null;
    const adv = Math.max(...pays); const hay = `${ttl} ${desc}`.toLowerCase();
    let best = null, bestLen = 0;
    for (const k in BLS) for (const kw of BLS[k][2]) if (hay.includes(kw) && kw.length > bestLen) { best = BLS[k]; bestLen = kw.length; }
    if (!best) return null;
    const ratio = adv / best[1];
    if (ratio < 1.8) return null;
    const detail = `advertised ~$${fmt0(adv)}/yr is ${ratio.toFixed(1)}x the national median of $${fmt0(best[1])} for ${best[0]}`;
    return F("pay_anomaly", "warning", 17, "The stated pay is out of band", detail + ". Figures far above market for the described work are the hook.", [detail]);
  }

  // ---------------- email domains ----------------
  const FREE_MAIL = new Set(["gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "aol.com", "protonmail.com", "proton.me", "mail.com", "yandex.com", "gmx.com", "icloud.com", "live.com", "msn.com"]);
  function emailDomains(text, company) {
    const ds = new Set((text.match(/[\w.+-]+@[\w-]+\.[\w.-]+/gi) || []).map(e => e.split("@")[1].toLowerCase().replace(/[.,;:]+$/, "")));
    const free = [...ds].filter(d => FREE_MAIL.has(d)).sort();
    if (free.length && company.trim())
      return [F("personal_email", "warning", 18, "Recruiter writing from a personal address",
        `Corporate hiring comes from the company's own domain. Nothing here comes from a ${company.trim()} address.`, free.map(d => "@" + d))];
    return [];
  }

  // ---------------- apply-link structure ----------------
  const NEUTRAL = ["linkedin.com", "indeed.com", "glassdoor.com", "ziprecruiter.com", "greenhouse.io", "lever.co", "workday.com", "myworkdayjobs.com", "smartrecruiters.com", "jobs.polymer.co", "polymer.co", "ashbyhq.com", "icims.com", "taleo.net", "bamboohr.com", "careers-page.com"];
  const TRACKING = new Set(["utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_category", "cpc", "affiliate", "extra_id_consumer_run", "extra_prev_uid", "extrlint"]);
  const URL_SPECS = {
    redirect_hop: ["note", 6, "The apply link passes through a redirect/tracking hop", "A redirect before the real listing is common for legitimate aggregators too, but it's worth knowing you're not going straight to the employer."],
    tracking_params: ["note", 5, "The apply link carries campaign tracking parameters", "UTM and similar tags mean this link is part of a marketing/affiliate campaign, not a direct posting from the employer."],
    paid_click: ["warning", 14, "The apply link is paid-per-click traffic", "A cost-per-click parameter means someone gets paid each time this link is clicked, regardless of whether you're hired -- that's an ad, not a job posting."],
    signup_wall: ["warning", 15, "An account signup is forced before you can see the listing", "Legitimate job boards let you see the posting before asking you to create an account. A forced signup wall exists to harvest your email and profile."],
    domain_mismatch: ["warning", 16, "The apply link doesn't lead to the claimed employer", "The application ultimately goes to a domain unrelated to the company the listing named, and it isn't a recognized job platform -- a sign you're dealing with a reposting or aggregator, not the employer directly."],
  };
  function splitUrl(url) {
    const m = /^[a-z][a-z0-9+.\-]*:\/\/([^/?#]*)([^?#]*)(?:\?([^#]*))?/i.exec(url || "");
    if (!m) return {host: "", path: "", params: new Set()};
    let host = m[1].toLowerCase(); if (host.startsWith("www.")) host = host.slice(4);
    const params = new Set((m[3] || "").split(/[&;]/).map(kv => kv.split("=")).filter(kv => kv[0] && kv.length > 1 && kv[1] !== "").map(kv => decodeURIComponent(kv[0]).toLowerCase()));
    return {host, path: (m[2] || "").toLowerCase(), params};
  }
  function urlChain(urls, company) {
    if (!urls || !urls.length) return [];
    const hits = {};
    const add = (k, d) => (hits[k] = hits[k] || []).push(d);
    for (const url of urls) {
      const {host, path, params} = splitUrl(url);
      if (["/away/", "/out/", "/click/", "/redirect/", "/go/"].some(x => path.includes(x))) add("redirect_hop", `${host}${path} is a redirect/tracking hop`);
      const tracked = [...params].filter(p => TRACKING.has(p)).sort();
      if (tracked.length) add("tracking_params", `${host} URL carries tracking params: ${tracked.join(", ")}`);
      if (params.has("cpc") || url.toLowerCase().includes("cpc")) add("paid_click", `${host} URL contains a cost-per-click parameter -- paid traffic arbitrage`);
      if (["/register", "/signup", "/sign-up", "/apply-with-ai", "/start_google_auth"].some(x => path.includes(x))) add("signup_wall", `${host}${path} forces account creation before showing the listing`);
    }
    const fin = splitUrl(urls[urls.length - 1]).host;
    if (urls.length === 1 && company.trim() && fin && !NEUTRAL.some(p => fin.endsWith(p))) {
      const ck = company.toLowerCase().replace(/[^a-z]/g, ""), dk = fin.split(".")[0].replace(/[^a-z]/g, "");
      if (ck.length > 3 && !(dk.includes(ck.slice(0, 6)) || ck.includes(dk.slice(0, 6))))
        add("domain_mismatch", `Final application domain (${fin}) doesn't match the claimed employer name (${company.trim()}) and isn't a known job platform`);
    }
    return Object.keys(hits).map(k => F("url_" + k, URL_SPECS[k][0], URL_SPECS[k][1], URL_SPECS[k][2], URL_SPECS[k][3], hits[k].slice(0, 3)));
  }

  // ---------------- lead-generation axis ----------------
  const URL_POINTS = {url_signup_wall: [4, "The apply link forces an account signup"], url_paid_click: [4, "The apply link is paid-per-click traffic"],
    url_tracking_params: [2, "The apply link carries campaign tracking parameters"], url_redirect_hop: [2, "The apply link passes through a redirect hop"],
    url_domain_mismatch: [3, "The apply link doesn't lead to the named employer"]};
  const LG_TEXT = [
    [/\b(?:we are|is|are)\s+not\s+the\s+employer(?:\s+of\s+record)?\b|\baggregat(?:or|ed)\b|\bcross-?posted\b/i, 3, "The listing describes itself as an aggregator"],
    [/\ba\s+(?:remote\s+|growing\s+|leading\s+)?(?:company|firm|organization|business)\s+(?:is\s+)?(?:seeking|looking|hiring)\b|\bour\s+client\b|\b(?:confidential|undisclosed)\s+(?:employer|company|client)\b/i, 2, "The employer is described but not named"],
    [/\bregardless\s+of\s+(?:your\s+)?experience\b/i, 1, "Generic 'regardless of experience' boilerplate"],
    [/\btaking\s+a\s+(?:minute|moment)\s+to\s+(?:fill\s+out|complete|finish)\s+our\s+(?:online\s+)?application\b/i, 4, "Boilerplate 'start a career, fill out our application' pitch with no real role"],
    [/\b(?:research|market\s+research|focus\s+group|survey)\s+panel(?:ist)?s?\b|\bpaid\s+(?:focus\s+groups?|surveys?|research\s+studies)\b|\btake\s+(?:paid\s+)?surveys?\b|\bfocus\s+group\s+(?:participants?|studies)\b/i, 4, "A survey or focus-group panel signup dressed up as a job"],
    [/\byou\s+will\s+receive\s+an\s+email\s+within\b|\bcheck\s+your\s+(?:inbox|email)\s+or\s+spam\b/i, 4, "An automated funnel that emails you right after you apply"],
    [/\bnot\s+a\s+salaried\s+job\b|\b(?:independent\s+)?(?:business|income)\s+opportunity\b|\bearnings\s+depend\s+on\s+your\b/i, 4, "An income or referral 'opportunity', not a job with an employer"],
    [/\bcreate\s+(?:your\s+)?(?:a\s+)?free\s+account\b|\bsign\s+up\s+(?:for\s+)?free\b/i, 2, "Asks you to create an account on a third-party site"],
    [/\bljbffr\b/i, 3, "Carries a scraped job ID from a reposting network"],
  ];
  const LG_VERDICT = "This looks like an aggregator or lead-generation listing: the link goes through a middleman, not the employer. It may collect your email and profile. Find the employer's own posting before you apply.";
  function leadGen(text, urlFindings) {
    let points = 0; const reasons = [];
    for (const f of urlFindings) { const s = URL_POINTS[f.rule_id]; if (s) { points += s[0]; reasons.push({source: "link", points: s[0], reason: s[1], matched: f.matched.slice(0, 2)}); } }
    const norm = normalize(text);
    for (const [rx, pts, reason] of LG_TEXT) { const m = rx.exec(norm); if (m) { points += pts; reasons.push({source: "text", points: pts, reason, matched: [m[0].slice(0, 80)]}); } }
    const flag = points >= 6;
    return {flag, level: points >= 8 ? "likely" : flag ? "possible" : null, points, reasons, verdict: flag ? LG_VERDICT : ""};
  }

  // ---------------- the scorer ----------------
  const SEV = {critical: 0, warning: 1, note: 2};
  const bySeverity = (a, b) => SEV[a.severity] - SEV[b.severity] || b.weight - a.weight;
  function band(score, critical) { return critical || score >= 65 ? "block" : score >= 35 ? "review" : score >= 15 ? "caution" : "clear"; }
  function scorePosting(ttl, description, company, urlChainList) {
    company = company || "";
    const full = `${ttl}\n${description}`;
    let findings = runTextRules(full);
    const h = impliedHourly(full); if (h) findings.push(h);
    findings = findings.concat(emailDomains(full, company));
    const c = compensation(ttl, description); if (c) findings.push(c);
    const fired = new Set(findings.map(f => f.rule_id));
    if (["banking_pii", "mule_recruitment", "off_platform"].filter(x => fired.has(x)).length >= 2)
      findings.push(F("mule_combo", "critical", 28, "Combined pattern: recruitment + banking/ID + off-platform",
        "This message combines a recruitment pitch, a request for banking or identity details, and a push to an outside app. Together these are the money-mule hiring scam - walk away.",
        ["multiple money-mule signals present together"]));
    const lead_gen = leadGen(full, urlChain(urlChainList || [], company));
    findings.sort(bySeverity);
    const score = Math.min(100, findings.reduce((s, f) => s + f.weight, 0));
    return {score, band: band(score, findings.some(f => f.severity === "critical")), findings, lead_gen, ruleset: RULEPACK.version};
  }

  // ---------------- "Is this a scam?" (msgcheck.py) ----------------
  const LEVELS = [
    ["ok", "No known scam signs", "Nothing here matches a known scam pattern. That isn't a guarantee: confirm the employer through their own website or the FSU Career Center before sharing personal details."],
    ["caution", "Be careful", "A few things are off. Verify the sender through an official channel you find yourself before you reply or click anything."],
    ["warn", "Likely a scam", "Several strong scam signals. Don't reply with personal information, don't click links, and don't send or accept money."],
    ["bad", "Scam. Stop here.", "This matches patterns that only scams use. Don't respond, don't click links, and never send money, gift cards, or bank details."],
  ];
  const BAND_LEVEL = {clear: 0, caution: 1, review: 2, block: 3};
  const SHORT = new Set(["bit.ly", "tinyurl.com", "t.co", "rb.gy", "cutt.ly", "shorturl.at", "is.gd", "ow.ly", "buff.ly", "tiny.cc", "rebrand.ly", "s.id", "t.ly", "lnkd.in", "shorturl.com", "bl.ink", "short.io"]);
  const CHAT = new Set(["wa.me", "chat.whatsapp.com", "t.me", "telegram.me", "signal.me", "m.me", "discord.gg"]);
  const FORMS = new Set(["forms.gle", "docs.google.com", "forms.office.com", "jotform.com", "typeform.com"]);
  const CLAIMS_SCHOOL = /\b(?:professor|prof\.|dr\.|department|dept\.?|university|career (?:center|services)|fsu|florida state|financial aid|registrar|dean|faculty|student employment)\b/i;
  const CLAIMS_COMPANY = /\b(?:hr|human resources|recruit(?:er|ing|ment)|talent acquisition|hiring manager|onboarding)\b/i;
  const URL_RX = /(?:https?:\/\/|www\.)[^\s<>"')\]]+/gi;
  const EMAIL_RX = /[\w.+-]+@([\w-]+(?:\.[\w-]+)+)/gi;
  const isFsu = d => { d = d.toLowerCase().replace(/\.$/, ""); return d === "fsu.edu" || d.endsWith(".fsu.edu"); };
  const looksFsu = d => { d = d.toLowerCase().replace(/\.$/, ""); if (isFsu(d)) return false; const f = d.replace(/[^a-z0-9]/g, ""); return f.includes("fsu") || f.includes("floridastate") || f.includes("seminole"); };
  function senderFindings(sender, text) {
    const out = []; sender = (sender || "").trim();
    const domains = new Set(allMatches(EMAIL_RX, sender + " " + text).map(m => m[1].toLowerCase()));
    const sm = new RegExp(EMAIL_RX.source, "i").exec(sender); const sd = sm ? sm[1].toLowerCase() : "";
    for (const d of [...domains].sort()) if (looksFsu(d))
      out.push(F("fsu_lookalike", "critical", 40, "An address pretends to be FSU", `${d} is not an FSU address. Real FSU email ends in exactly @fsu.edu (or a department subdomain like @cs.fsu.edu). Look-alike domains are a classic phishing move.`, ["@" + d]));
    if (FREE_MAIL.has(sd)) {
      const claim = CLAIMS_SCHOOL.exec(text + " " + sender) || CLAIMS_COMPANY.exec(text + " " + sender);
      if (claim) out.push(F("personal_sender", "warning", 18, "Official-sounding message from a personal account", `It claims to be a ${claim[0].toLowerCase()} but was sent from ${sd}. Universities and real companies write from their own domain.`, ["@" + sd]));
    }
    if (sender && /\b(?:fsu|florida state|career center)\b/i.test(sender) && sd && !isFsu(sd))
      out.push(F("display_spoof", "warning", 20, "The sender name says FSU but the address doesn't", `The name shown mentions FSU, but the address is at ${sd}.`, [sender.slice(0, 80)]));
    return out;
  }
  function linkFindings(text) {
    const out = [], seen = new Set();
    for (const m of allMatches(URL_RX, text || "")) {
      const raw = m[0]; const url = raw.toLowerCase().startsWith("http") ? raw : "http://" + raw;
      let host = (/^https?:\/\/(?:[^@\/?#]*@)?(\[[^\]]*\]|[^:\/?#]*)/i.exec(url) || [,""])[1].toLowerCase();
      if (host.startsWith("www.")) host = host.slice(4);
      if (!host || seen.has(host)) continue; seen.add(host);
      const ev = [raw.slice(0, 80)];
      if (SHORT.has(host)) out.push(F("short_link", "warning", 14, "A shortened link hides where it goes", `${host} links hide the real destination. Don't open it; ask for the company's own site instead.`, ev));
      else if (CHAT.has(host)) out.push(F("chat_link", "warning", 18, "Pushes you to a chat app", "Moving a 'job' to WhatsApp, Telegram or Signal is how scammers avoid the platforms that screen them.", ev));
      else if (/^\d{1,3}(?:\.\d{1,3}){3}$/.test(host)) out.push(F("ip_link", "critical", 34, "A link to a bare IP address", "Real employers don't send links to raw number addresses.", ev));
      else if (looksFsu(host)) out.push(F("fsu_lookalike_link", "critical", 40, "A link pretends to be FSU", `${host} is not an FSU website. FSU sites end in fsu.edu.`, ev));
      else if (FORMS.has(host) || host.endsWith(".jotform.com")) out.push(F("form_link", "note", 8, "Asks you to fill in an outside form", "Forms are fine for events, but a 'job' that starts with a form asking for your details is a common data-harvesting step.", ev));
    }
    return out;
  }
  function check(text, sender) {
    text = (text || "").trim().slice(0, 8000); sender = (sender || "").trim().slice(0, 200);
    const r = scorePosting("", text + (sender ? "\n" + sender : ""), "", null);
    const best = new Map();
    for (const f of r.findings.concat(senderFindings(sender, text), linkFindings(text)))
      if (!best.has(f.rule_id) || f.weight > best.get(f.rule_id).weight) best.set(f.rule_id, f);
    const findings = [...best.values()].sort(bySeverity);
    const score = Math.min(100, findings.reduce((s, f) => s + f.weight, 0));
    const b = band(score, findings.some(f => f.severity === "critical"));
    let level = BAND_LEVEL[b];
    if (r.lead_gen.flag && level < 1) level = 1;
    const [key, ttl, advice] = LEVELS[level];
    return {level, key, title: ttl, advice, score, band: b, findings, lead_gen: r.lead_gen};
  }
  const NEXT_STEPS = [
    ["Look the company up yourself (not through links in the message) and confirm the job is on their careers page.", "Keep the conversation on NoleCareerShield, Handshake or the company's own email.", "Never pay for training, equipment or a background check. Real jobs don't charge you."],
    ["Don't click links or open attachments yet.", "Find the organization's official contact on your own (their website, the FSU directory) and ask if the message is real.", "Don't share your student ID, date of birth, SSN or bank details.", "Check again here if they reply with anything new."],
    ["Don't reply with personal information, and don't click the links.", "If it claims to be from FSU, forward it to FSU's IT security team and delete it.", "Block the sender. If it came through NoleCareerShield, press Report so reviewers can remove them."],
    ["Stop replying. Don't send money, gift cards, crypto, or bank details, and don't deposit any check they send.", "If you already shared banking details or deposited a check, call your bank now.", "Report it: forward FSU look-alikes to FSU's IT security team, and report fraud at reportfraud.ftc.gov.", "If it came through NoleCareerShield, press Report so reviewers can remove the account."],
  ];

  // ---------------- matching (matching.py) ----------------
  const SKILLS = {
    "Excel": ["excel", "spreadsheets", "spreadsheet", "vlookup", "xlookup", "pivot tables", "pivot table"],
    "SQL": ["sql", "mysql", "postgresql", "postgres", "sqlite", "t-sql", "pl/sql", "sql server"],
    "Python": ["python", "pandas", "numpy", "jupyter"], "R": ["r programming", "rstudio", "tidyverse", "ggplot"],
    "Tableau": ["tableau"], "Power BI": ["power bi", "powerbi"],
    "Data analysis": ["data analysis", "data analytics", "analyzing data", "analyze data", "data analyst"],
    "Data visualization": ["data visualization", "dashboards", "dashboard", "data viz"],
    "Statistics": ["statistics", "statistical analysis", "regression", "hypothesis testing"],
    "SPSS": ["spss"], "Stata": ["stata"], "SAS": ["sas programming", "sas enterprise", "base sas"],
    "Machine learning": ["machine learning", "scikit-learn", "sklearn", "deep learning", "pytorch", "tensorflow"],
    "Data entry": ["data entry", "typing"], "Google Analytics": ["google analytics", "ga4"],
    "Java": ["java"], "JavaScript": ["javascript", "js", "node.js", "nodejs", "typescript"],
    "React": ["react", "react.js", "reactjs", "next.js"], "HTML/CSS": ["html", "css", "html/css"],
    "C++": ["c++", "cpp"], "C#": ["c#", ".net", "dotnet"], "Go": ["golang"], "Swift": ["swift", "ios development"],
    "Kotlin": ["kotlin", "android development"], "PHP": ["php", "laravel"], "Ruby": ["ruby", "rails"],
    "Git": ["git", "github", "gitlab", "version control"], "Linux": ["linux", "unix", "bash", "shell scripting"],
    "AWS": ["aws", "amazon web services", "ec2", "s3"], "Azure": ["azure"], "Docker": ["docker", "kubernetes", "containers"],
    "APIs": ["api", "apis", "rest api", "restful"], "Cybersecurity": ["cybersecurity", "cyber security", "information security", "infosec", "security+"],
    "Networking": ["networking", "tcp/ip", "network administration", "ccna"], "IT support": ["help desk", "helpdesk", "it support", "technical support", "troubleshooting"],
    "Web development": ["web development", "web developer", "front-end", "frontend", "back-end", "backend", "full stack", "full-stack"],
    "MATLAB": ["matlab"], "CAD": ["cad", "autocad", "solidworks", "fusion 360"],
    "Microsoft Office": ["microsoft office", "ms office", "office 365", "microsoft 365", "microsoft word", "ms word", "outlook", "microsoft access"],
    "PowerPoint": ["powerpoint", "presentations", "slide decks"],
    "Google Workspace": ["google workspace", "google docs", "google sheets", "g suite", "gsuite"],
    "Scheduling": ["scheduling", "calendar management", "appointment setting"],
    "Project management": ["project management", "asana", "trello", "jira", "agile", "scrum"],
    "Bookkeeping": ["bookkeeping", "quickbooks", "accounts payable", "accounts receivable", "invoicing", "reconciliation"],
    "Accounting": ["accounting", "gaap", "general ledger", "financial statements", "audit"],
    "Financial modeling": ["financial modeling", "financial analysis", "valuation", "dcf", "forecasting", "budgeting"],
    "Salesforce": ["salesforce", "crm"], "HubSpot": ["hubspot"],
    "Sales": ["sales", "selling", "lead generation", "cold calling", "business development"],
    "Customer service": ["customer service", "customer support", "client service", "guest service", "customer experience"],
    "Cash handling": ["cash handling", "cashier", "point of sale", "pos system", "cash register"],
    "Inventory": ["inventory", "stocking", "warehouse", "shipping and receiving", "forklift", "logistics"],
    "Event planning": ["event planning", "event coordination", "events"],
    "Social media": ["social media", "instagram", "tiktok", "facebook", "linkedin marketing", "content calendar"],
    "Marketing": ["marketing", "digital marketing", "brand", "campaigns", "market research"],
    "SEO": ["seo", "search engine optimization", "sem", "google ads"],
    "Email marketing": ["email marketing", "mailchimp", "newsletters"],
    "Content writing": ["content writing", "copywriting", "blog", "blogging", "writing", "editing", "proofreading"],
    "Graphic design": ["graphic design", "adobe illustrator", "illustrator", "indesign", "canva", "figma", "photoshop"],
    "Video editing": ["video editing", "premiere pro", "final cut", "after effects", "davinci resolve"],
    "Photography": ["photography", "photo editing", "lightroom"],
    "UX design": ["ux", "ui/ux", "user research", "wireframes", "prototyping", "usability testing"],
    "Research": ["research", "literature review", "research assistant"],
    "Lab skills": ["laboratory", "lab techniques", "pcr", "cell culture", "pipetting", "wet lab"],
    "Patient care": ["patient care", "cna", "medical assistant", "vital signs", "clinical"],
    "HIPAA": ["hipaa"], "CPR/First aid": ["cpr", "first aid", "bls certification"],
    "Tutoring": ["tutoring", "tutor", "teaching", "mentoring", "instruction", "lesson planning"],
    "Childcare": ["childcare", "child care", "babysitting", "camp counselor"],
    "Communication": ["communication skills", "written communication", "verbal communication", "public speaking"],
    "Leadership": ["leadership", "team lead", "supervised", "managed a team", "president", "officer"],
    "Teamwork": ["teamwork", "collaboration", "cross-functional"],
    "Problem solving": ["problem solving", "problem-solving", "critical thinking", "analytical skills"],
    "Time management": ["time management", "organization skills", "organizational skills", "multitasking", "detail oriented", "detail-oriented"],
    "Spanish": ["spanish", "bilingual"], "French": ["french"], "Mandarin": ["mandarin", "chinese"], "Portuguese": ["portuguese"],
    "Food service": ["food service", "barista", "restaurant server", "serving", "food handling", "restaurant", "kitchen"],
    "Driving": ["driver's license", "drivers license", "valid license", "delivery driver"],
  };
  const POPULAR = ["Excel", "SQL", "Python", "Microsoft Office", "Google Workspace", "Customer service", "Communication", "Social media", "Marketing", "Content writing", "Graphic design", "Data analysis", "Research", "Tutoring", "Sales", "Leadership", "Teamwork", "Time management", "Spanish", "Event planning", "JavaScript", "HTML/CSS", "Tableau", "Bookkeeping", "Video editing", "Cash handling", "Project management", "Problem solving"];
  const CATEGORY_WORDS = {
    "Data & Analytics": ["data", "analytics", "analyst", "sql", "excel", "tableau", "power bi", "statistics", "dashboard"],
    "Software & IT": ["software", "developer", "engineer", "programming", "coding", "it ", "help desk", "web", "cyber", "tech"],
    "Admin & Office": ["admin", "administrative", "office", "receptionist", "front desk", "clerical", "assistant"],
    "Customer Service": ["customer service", "customer support", "call center", "guest"],
    "Sales": ["sales", "business development", "account"],
    "Marketing": ["marketing", "social media", "brand", "content", "seo", "communications", "pr "],
    "Finance & Accounting": ["finance", "accounting", "bookkeeping", "tax", "audit", "banking", "financial"],
    "Research": ["research", "lab", "study", "laboratory"],
    "Education & Tutoring": ["tutor", "tutoring", "teaching", "education", "mentor", "camp"],
    "Healthcare": ["health", "medical", "patient", "clinic", "nurse", "pharmacy", "hospital"],
    "Creative & Design": ["design", "graphic", "video", "photo", "creative", "art", "writer", "writing"],
    "Hospitality & Food": ["restaurant", "barista", "server", "hospitality", "hotel", "food", "catering"],
    "Operations & Warehouse": ["warehouse", "operations", "logistics", "delivery", "driver", "inventory"],
    "Campus Jobs": ["on campus", "on-campus", "campus", "university", "federal work study", "work-study", "ops student"],
  };
  const CATEGORIES = Object.keys(CATEGORY_WORDS).concat(["Other"]);
  const WORK_TYPES = ["remote", "hybrid", "on-site"];
  const JOB_KINDS = ["internship", "part-time", "full-time", "on-campus"];
  const MAJOR_HINTS = [
    [["computer science", "software", "computer engineering", "information technology", "cyber", "information science"], ["Software & IT", "Data & Analytics"]],
    [["statistic", "math", "data science", "actuarial"], ["Data & Analytics", "Research", "Finance & Accounting"]],
    [["finance", "accounting", "economics", "real estate", "risk management"], ["Finance & Accounting", "Data & Analytics"]],
    [["marketing", "advertising", "public relations", "communication", "media", "journalism"], ["Marketing", "Creative & Design", "Sales"]],
    [["business", "management", "entrepreneur", "supply chain", "hospitality"], ["Admin & Office", "Sales", "Operations & Warehouse", "Hospitality & Food"]],
    [["biology", "chemistry", "biochem", "neuroscience", "physics", "psychology", "exercise", "nutrition", "public health"], ["Research", "Healthcare"]],
    [["nursing", "health", "pre-med", "premed", "kinesiology"], ["Healthcare", "Research"]],
    [["education", "teaching", "english", "history", "philosophy"], ["Education & Tutoring", "Creative & Design"]],
    [["art", "design", "film", "music", "theatre", "theater", "studio", "graphic"], ["Creative & Design", "Marketing"]],
    [["engineering"], ["Software & IT", "Research"]],
  ];
  const WT_WORDS = {"remote": ["remote", "from home", "wfh", "online", "virtual"], "hybrid": ["hybrid"], "on-site": ["on-site", "onsite", "in person", "in-person", "near campus", "on campus", "tallahassee"]};
  const KIND_WORDS = {"internship": ["intern", "internship", "co-op"], "part-time": ["part-time", "part time", "flexible hours", "evenings", "weekends"], "full-time": ["full-time", "full time", "new grad", "entry-level", "entry level"], "on-campus": ["on campus", "on-campus", "work-study", "work study"]};
  const STOP = new Set(`a an the and or for to of in on at with from by i im i'm me my we our you your find show get looking look want need
jobs job any some something that this those these is are be can could would like please roles role position positions work working
opportunities opportunity near around under over about good best new latest open openings hiring help me what which who where how
do does using use used also just really kind type sort some part time full remote hybrid onsite on-site person campus internship internships intern interns`.split(/\s+/));
  const SKILL_RX = Object.entries(SKILLS).map(([canon, ph]) => {
    let alts = [...new Set(ph.concat([canon]).map(p => p.toLowerCase()))].sort((a, b) => b.length - a.length);
    if (canon === "R" || canon === "Go") alts = alts.filter(a => a !== "r" && a !== "go");
    return [canon, new RegExp("(?<![\\w+#.])(?:" + alts.map(reEsc).join("|") + ")(?![\\w+#])", "i")];
  });
  function extractSkills(text) {
    const found = [];
    for (const [c, rx] of SKILL_RX) { const m = rx.exec(text || ""); if (m) found.push([m.index, c]); }
    return found.sort((a, b) => a[0] - b[0] || (a[1] < b[1] ? -1 : 1)).map(x => x[1]);
  }
  function normalizeSkill(v) {
    v = (v || "").trim().replace(/\s+/g, " ").slice(0, 40); if (!v) return null;
    const hits = extractSkills(v); return hits.length && v.length <= 30 ? hits[0] : v;
  }
  function categoriesForMajor(major) {
    const m = (major || "").toLowerCase(), out = [];
    for (const [keys, cats] of MAJOR_HINTS) if (keys.some(k => m.includes(k))) for (const c of cats) if (!out.includes(c)) out.push(c);
    return out;
  }
  function profileSkillset(p) {
    if (!p) return new Set();
    const s = new Set((p.skills || []).filter(x => typeof x === "string"));
    extractSkills(p.resume_text || "").forEach(x => s.add(x));
    extractSkills((p.headline || "") + " " + (p.bio || "")).forEach(x => s.add(x));
    return s;
  }
  function parseQuery(text) {
    const t = " " + (text || "").toLowerCase() + " ";
    const work_type = Object.keys(WT_WORDS).find(k => WT_WORDS[k].some(w => t.includes(w))) || "";
    const kinds = Object.keys(KIND_WORDS).filter(k => KIND_WORDS[k].some(w => t.includes(w)));
    let category = "", best = 0;
    for (const [cat, words] of Object.entries(CATEGORY_WORDS)) { const n = words.filter(w => t.includes(w)).length; if (n > best) { best = n; category = cat; } }
    const words = (t.match(/[a-z][a-z+#.\-]{1,30}/g) || []).filter(w => !STOP.has(w));
    return {work_type, kinds, category, skills: extractSkills(text), keywords: words.slice(0, 8)};
  }
  function rankJobs(jobs, profile, query, limit, strict) {
    query = query || ""; limit = limit || 10; strict = strict !== false;
    const us = profileSkillset(profile), interests = new Set((profile || {}).interests || []);
    const majorCats = new Set(categoriesForMajor((profile || {}).major));
    const prefTypes = new Set((profile || {}).work_types || []), prefKinds = (profile || {}).job_kinds || [];
    const q = query.trim() ? parseQuery(query) : null;
    const out = [];
    for (const j of jobs) {
      const text = `${j.title || ""}\n${j.description || ""}`, low = " " + text.toLowerCase() + " ", tl = (j.title || "").toLowerCase();
      const js = extractSkills(text), matched = js.filter(s => us.has(s)), missing = js.filter(s => !us.has(s));
      const reasons = []; let score = 0;
      if (js.length && us.size) { score += 45 * Math.min(1, matched.length / Math.max(3, js.length) * 1.25); if (matched.length) reasons.push("Uses your skills: " + matched.slice(0, 4).join(", ")); }
      else if (us.size) score += 6;
      if (interests.has(j.category)) { score += 15; reasons.push(`In ${j.category}, one of your interests`); }
      else if (majorCats.has(j.category)) { score += 8; reasons.push(`Fits your major (${profile.major})`); }
      if (prefTypes.size && prefTypes.has(j.work_type)) { score += 10; reasons.push(`${title(j.work_type)}, as you prefer`); }
      for (const k of prefKinds) if ((KIND_WORDS[k] || []).some(w => low.includes(w))) { score += 6; reasons.push(title(k.replace("-", " ")) + " role"); break; }
      if (q) {
        const hit = [];
        for (const w of q.keywords) { if (tl.includes(w)) { score += 9; hit.push(w); } else if (low.includes(" " + w)) { score += 3; hit.push(w); } }
        for (const s of q.skills) if (js.includes(s) && !hit.includes(s.toLowerCase())) { score += 8; hit.push(s); }
        if (q.category && j.category === q.category) { score += 10; hit.push(q.category); }
        if (q.work_type) { if (j.work_type === q.work_type) { score += 10; hit.push(q.work_type); } else if (strict) continue; }
        let wrongKind = false;
        for (const k of q.kinds) { if (KIND_WORDS[k].some(w => low.includes(w))) { score += 8; hit.push(k); } else if (strict && k === "internship") wrongKind = true; }
        if (wrongKind) continue;
        if (strict && (q.keywords.length || q.skills.length || q.category) && !hit.length) continue;
        if (hit.length) reasons.unshift("Matches “" + [...new Set(hit.slice(0, 3))].join(", ") + "”");
      }
      score += j.scam_status === "clear" ? 3 : -4;
      score += Math.max(0, 5 - (j.age_days || 0) / 6);
      out.push({job: j, score: Math.max(0, Math.min(100, Math.round(score))), reasons: reasons.slice(0, 3), matched, missing: missing.slice(0, 6)});
    }
    out.sort((a, b) => b.score - a.score || (b.job.id - a.job.id));
    return out.slice(0, limit);
  }
  function keywordGap(resume, jobText) {
    const job = extractSkills(jobText), have = new Set(extractSkills(resume));
    const present = job.filter(s => have.has(s)), missing = job.filter(s => !have.has(s));
    return {job_skills: job, present, missing, match_pct: job.length ? Math.round(100 * present.length / job.length) : 0};
  }

  // ---------------- resume (resume_engine.py) ----------------
  const SECTION_NAMES = {
    education: ["education", "academic background", "academics"],
    experience: ["experience", "work experience", "professional experience", "employment", "work history", "relevant experience", "internships", "internship experience"],
    projects: ["projects", "academic projects", "personal projects", "selected projects", "research", "research experience"],
    skills: ["skills", "technical skills", "skills & interests", "skills and interests", "core skills", "tools", "technologies"],
    leadership: ["leadership", "leadership experience", "activities", "involvement", "campus involvement", "extracurricular activities", "organizations", "volunteer", "volunteer experience", "service"],
    awards: ["awards", "honors", "honors & awards", "honors and awards", "certifications", "certificates"],
    summary: ["summary", "profile", "professional summary", "objective", "career objective"],
    coursework: ["relevant coursework", "coursework"],
  };
  const HEADING = {}; for (const k in SECTION_NAMES) for (const n of SECTION_NAMES[k]) HEADING[n] = k;
  const STRONG = new Set(`accelerated achieved administered advised advocated analyzed answered architected arranged assembled assessed audited
authored automated balanced boosted briefed budgeted built calculated campaigned captured catalogued chaired championed
clarified coached collaborated collected compiled completed composed computed conceived conducted configured consolidated
constructed consulted converted coordinated corrected counseled created cultivated curated cut debugged decreased defined
delivered demonstrated deployed designed detected determined developed devised diagnosed directed discovered documented
drafted drove edited educated eliminated enabled engineered enhanced established evaluated examined executed expanded
expedited facilitated filmed forecasted formulated founded gathered generated grew guided handled headed hired identified
illustrated implemented improved increased influenced informed initiated inspected installed instructed integrated interpreted
interviewed introduced invented investigated launched led lectured logged maintained managed mapped marketed maximized measured
mediated mentored merged migrated minimized modeled monitored motivated negotiated obtained operated optimized orchestrated organized
oversaw partnered performed persuaded photographed piloted pitched planned prepared presented prioritized processed produced
programmed promoted proposed prototyped provided published qualified quantified raised ran rebuilt recommended reconciled recorded
recruited redesigned reduced refined reorganized repaired reported represented researched resolved restructured revamped reviewed
revised saved scheduled screened secured served shaped simplified sold solved spearheaded standardized started streamlined
strengthened structured supervised supported surveyed synthesized taught tested tracked trained transformed translated tutored
unified updated upgraded validated verified volunteered won wrote`.split(/\s+/));
  const WEAK = [[/^(?:was\s+)?responsible\s+for\s+/, ""], [/^duties\s+(?:included|include)\s*:?\s*/, ""], [/^tasked\s+with\s+/, ""],
    [/^in\s+charge\s+of\s+/, "Led "], [/^helped\s+(?:with\s+|to\s+)?/, "Supported "], [/^assisted\s+(?:with\s+|in\s+)?/, "Supported "],
    [/^worked\s+on\s+/, "Developed "], [/^worked\s+with\s+/, "Collaborated with "], [/^participated\s+in\s+/, "Contributed to "],
    [/^involved\s+in\s+/, "Contributed to "], [/^did\s+/, "Completed "], [/^handled\s+/, "Managed "]];
  const BUZZ = ["hard-working", "hardworking", "team player", "go-getter", "detail-oriented", "detail oriented", "self-starter", "results-driven", "synergy", "think outside the box", "passionate", "dynamic individual", "motivated individual", "people person", "fast learner", "quick learner", "go getter", "rockstar", "ninja"];
  const IRREG = {writing: "Wrote", leading: "Led", making: "Made", building: "Built", teaching: "Taught", running: "Ran", selling: "Sold", speaking: "Spoke", taking: "Took", giving: "Gave", keeping: "Kept", meeting: "Met", finding: "Found", bringing: "Brought", holding: "Held", setting: "Set", putting: "Put", cutting: "Cut", getting: "Got", driving: "Drove", drawing: "Drew", doing: "Completed", having: "Had", overseeing: "Oversaw", shooting: "Shot", winning: "Won", paying: "Paid", saying: "Said"};
  const BULLET = /^\s*(?:[•▪●◦‣■\-*–]|o\s)\s*/;
  const NUM = /\d|%|\$|\b(?:dozens?|hundreds?|thousands?|twice|double[ds]?|tripled?|half)\b/i;
  const PRONOUN = /\b(?:I|me|my|mine|we|our)\b/;
  const DATE_TAIL = /(?:19|20)\d{2}|present|current/i;
  function heading(line) { const t = line.trim().toLowerCase().replace(/[^a-z& ]/g, "").trim(); return t.length > 2 && t.length <= 40 && HEADING[t] ? HEADING[t] : null; }
  function parse(text) {
    const lines = (text || "").split(/\r?\n/).map(l => l.replace(/\s+$/, ""));
    const sections = {}; let cur = "header"; let bullets = [];
    lines.forEach((ln, i) => {
      if (!ln.trim()) return;
      const h = heading(ln); if (h) { if (!(h in sections)) sections[h] = i; cur = h; return; }
      if (BULLET.test(ln)) bullets.push({line: i, text: ln.replace(BULLET, "").trim(), section: cur});
    });
    if (!bullets.length) {
      cur = "header";
      lines.forEach((ln, i) => {
        const h = heading(ln); if (h) { cur = h; return; }
        if (["experience", "projects", "leadership"].includes(cur) && ln.split(/\s+/).filter(Boolean).length >= 6 && !DATE_TAIL.test(ln.slice(-14)))
          bullets.push({line: i, text: ln.trim(), section: cur});
      });
    }
    return {lines, sections, bullets: bullets.filter(b => b.text)};
  }
  const firstWord = t => { const m = /^[A-Za-z][A-Za-z'-]*/.exec(t.trim()); return m ? m[0].toLowerCase() : ""; };
  function gerundToPast(w) {
    w = w.toLowerCase(); if (IRREG[w]) return IRREG[w];
    if (w.endsWith("ing") && w.length > 5) { const st = w.slice(0, -3); const p = st.endsWith("y") && !"aeiou".includes(st.slice(-2, -1)) ? st.slice(0, -1) + "ied" : st + "ed"; return p[0].toUpperCase() + p.slice(1); }
    return null;
  }
  function bulletIssues(text) {
    const iss = [], first = firstWord(text), low = text.toLowerCase();
    if (WEAK.some(([rx]) => rx.test(low))) iss.push("Starts with a weak phrase. Lead with what you did.");
    else if (first && !STRONG.has(first) && !first.endsWith("ed")) iss.push("Start with a strong past-tense verb (Led, Built, Analyzed...).");
    if (!NUM.test(text)) iss.push("No number. How many, how much, or how often?");
    const n = text.split(/\s+/).filter(Boolean).length;
    if (n > 34) iss.push(`Long (${n} words). Aim for one line or two, under ~30 words.`); else if (n < 5) iss.push("Very short. Add what you did and what came of it.");
    if (PRONOUN.test(text)) iss.push("Drop I/my/we; resumes are written without pronouns.");
    const b = BUZZ.find(x => low.includes(x)); if (b) iss.push(`“${b}” is a claim. Show it with an example instead.`);
    return iss;
  }
  function improveBullet(text) {
    let t = (text || "").replace(BULLET, "").trim().replace(/\.+$/, ""); const original = t;
    t = t.replace(/^(?:I|We)\s+/, "").replace(/^(?:was|were|am)\s+(?=(?:in\s+charge|responsible|tasked|involved)\b)/i, "");
    const low = t.toLowerCase();
    for (const [rx, repl] of WEAK) {
      const m = rx.exec(low);
      if (m) { const rest = t.slice(m[0].length), nxt = firstWord(rest);
        if (["", "Led ", "Managed "].includes(repl) && nxt && gerundToPast(nxt)) t = rest;
        else if (repl === "Supported " && nxt.endsWith("ing")) t = "Assisted in " + rest;
        else t = (repl || "Managed ") + rest;
        break; }
    }
    const first = firstWord(t), past = first ? gerundToPast(first) : null;
    if (past) t = past + t.slice(first.length);
    t = t.replace(/\b(?:my|our)\s+/g, "the "); t = t ? t[0].toUpperCase() + t.slice(1) : t;
    const tips = [];
    if (!NUM.test(t)) { tips.push("Add a number: people served, dollars, hours saved, % change, or how often."); t += " [add a number: how many, how much, or how often]"; }
    if (!/\b(?:resulting|which|leading to|so that|to (?:increase|reduce|improve|help|support|save))\b/i.test(t)) tips.push("Say what changed because of your work (the result).");
    for (const b of BUZZ) if (t.toLowerCase().includes(b)) tips.push(`Cut “${b}” and show it with a detail.`);
    return {original, rewrite: t, tips: tips.slice(0, 3)};
  }
  function review(text) {
    text = text || ""; const p = parse(text), bullets = p.bullets, secs = p.sections;
    const words = (text.match(/\b\w+\b/g) || []).length, findings = [];
    const note = (severity, message) => findings.push({severity, message});
    const nb = bullets.length, quant = bullets.filter(b => NUM.test(b.text)).length, qr = nb ? quant / nb : 0;
    const impact = nb ? Math.round(25 * Math.min(1, qr / 0.5)) : 5;
    if (nb && qr < 0.4) note("warn", `Only ${quant} of ${nb} bullets have a number. Aim for at least half.`);
    const strong = bullets.filter(b => !bulletIssues(b.text).some(i => i.startsWith("Starts with a weak") || i.startsWith("Start with a strong"))).length;
    const vr = nb ? strong / nb : 0, verbs = nb ? Math.round(20 * vr) : 4;
    const starts = bullets.map(b => firstWord(b.text));
    const repeated = [...new Set(starts.filter(w => w && starts.filter(x => x === w).length >= 3))].sort();
    if (nb && vr < 0.7) note("warn", `${nb - strong} bullet${nb - strong !== 1 ? "s don" : " doesn"}'t start with a strong verb.`);
    if (repeated.length) note("info", "You start several bullets with the same verb (" + repeated.map(w => w[0].toUpperCase() + w.slice(1)).join(", ") + "). Vary them.");
    let structure = 0;
    if (/[\w.+-]+@[\w-]+\.[\w.-]+/.test(text)) structure += 2; else note("bad", "No email address. Put one at the top.");
    if (/(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}/.test(text)) structure += 1; else note("info", "No phone number. Many employers still call.");
    if (/linkedin\.com\/in\//i.test(text)) structure += 1; else note("info", "Add your LinkedIn URL (linkedin.com/in/...).");
    if ("education" in secs) { structure += 6; if (!/(?:19|20)\d{2}/.test(p.lines.slice(secs.education, secs.education + 8).join("\n"))) note("warn", "Add your graduation month and year (e.g. Expected May 2027)."); }
    else note("bad", "No Education section. For students it usually goes near the top.");
    if ("experience" in secs || "projects" in secs || "leadership" in secs) structure += 6; else note("bad", "No Experience, Projects or Leadership section found.");
    if ("skills" in secs) structure += 4; else note("warn", "Add a Skills section so screeners and ATS software find your tools.");
    let length = 0;
    if (words >= 250 && words <= 750) length += 8;
    else if (words < 250) { length += 4; note("warn", `Short (${words} words). Add projects, coursework or campus involvement.`); }
    else { length += words <= 950 ? 3 : 1; note("warn", `Long (${words} words). As a student, fit it on one page.`); }
    const okLen = bullets.filter(b => { const n = b.text.split(/\s+/).length; return n >= 5 && n <= 34; }).length;
    length += nb ? Math.round(7 * okLen / nb) : 2;
    if (nb < 4) note("warn", "Fewer than 4 bullet points. Describe each role with 2 to 4 bullets.");
    let clarity = 10; const pron = bullets.filter(b => PRONOUN.test(b.text));
    if (pron.length) { clarity -= 4; note("info", `${pron.length} bullet${pron.length !== 1 ? "s use" : " uses"} I/my/we. Drop the pronouns.`); }
    const buzz = [...new Set(BUZZ.filter(b => text.toLowerCase().includes(b)))].sort();
    if (buzz.length) { clarity -= 3; note("info", "Buzzwords to replace with evidence: " + buzz.slice(0, 4).join(", ") + "."); }
    if (repeated.length) clarity -= 3;
    let safety = 10;
    if (/\b\d{3}-\d{2}-\d{4}\b/.test(text)) { safety = 0; note("bad", "Remove what looks like a Social Security number. No resume should include one."); }
    if (/\b(?:date of birth|d\.o\.b|dob|birthdate|marital status|age\s*:)\b/i.test(text)) { safety -= 6; note("bad", "Remove date of birth, age or marital status. Employers don't need them, and scammers do."); }
    if (/\b\d{2,6}\s+[A-Za-z0-9.' ]{2,30}\s(?:st|street|ave|avenue|rd|road|blvd|drive|dr|lane|ln|way|ct|court|apt|circle|cir)\b\.?/i.test(text)) { safety -= 2; note("info", "Consider listing just your city and state instead of a street address."); }
    safety = Math.max(0, safety);
    const cats = [["Impact (numbers)", impact, 25], ["Action verbs", verbs, 20], ["Sections & contact", structure, 20], ["Length & readability", length, 15], ["Clarity", Math.max(0, clarity), 10], ["Privacy & safety", safety, 10]].map(([name, score, max]) => ({name, score, max}));
    const total = cats.reduce((s, c) => s + c.score, 0);
    const grade = total >= 85 ? "Strong" : total >= 70 ? "Solid" : total >= 55 ? "Needs work" : "Early draft";
    const items = [];
    for (const b of bullets) { const iss = bulletIssues(b.text); if (iss.length) { const ib = improveBullet(b.text); items.push({text: b.text, issues: iss, rewrite: ib.rewrite, tips: ib.tips}); } }
    const ord = {bad: 0, warn: 1, info: 2}; findings.sort((a, b) => ord[a.severity] - ord[b.severity]);
    return {score: total, grade, categories: cats, findings, bullets: items.slice(0, 12), stats: {words, bullets: nb, quantified: quant}, skills: extractSkills(text)};
  }
  const GENERIC = new Set(`about above across after also among an and any are as at be been being below between both but by can candidate
candidates company could day days do duties each ensure etc experience for from full has have help hours if in including into is it
its job join looking may more most must new not of on one or other our part per plus preferred position provide related required
requirements responsibilities role skills strong such team than that the their them there these they this through time to under
up us using we well what when where which who will with within work working years you your able ability students student
opportunity apply applicants including knowledge excellent good great including various other`.split(/\s+/));
  function keywords(text, n) {
    const freq = new Map();
    for (const w of ((text || "").toLowerCase().match(/[a-z][a-z\-]{3,}/g) || [])) if (!GENERIC.has(w)) freq.set(w, (freq.get(w) || 0) + 1);
    return [...freq.entries()].sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1)).filter(e => e[1] >= 2).map(e => e[0]).slice(0, n || 14);
  }
  function tailor(resume, jobTitle, jobText, profile) {
    const gap = keywordGap(resume, jobTitle + "\n" + jobText), kws = keywords(jobTitle + " " + jobText), lr = (resume || "").toLowerCase();
    const kp = kws.filter(k => lr.includes(k)), km = kws.filter(k => !lr.includes(k)), kwPct = kws.length ? Math.round(100 * kp.length / kws.length) : 0;
    const match = gap.job_skills.length ? Math.round(0.65 * gap.match_pct + 0.35 * kwPct) : kwPct;
    const terms = new Set(kws.concat(gap.job_skills.map(s => s.toLowerCase())));
    const scored = [];
    for (const b of parse(resume).bullets) { const low = b.text.toLowerCase(); const hits = [...terms].filter(t => low.includes(t)); if (hits.length) scored.push([hits.length, b.text, hits]); }
    scored.sort((a, b) => b[0] - a[0]);
    const lead = scored.slice(0, 4).map(([, t, h]) => ({text: t, why: "Mentions " + h.sort().slice(0, 3).join(", ")}));
    const p = profile || {}; const who = p.major ? `${p.major} student` : "Student", when = p.grad_term ? ` graduating ${p.grad_term}` : "";
    const strengths = gap.present.slice(0, 3).length ? gap.present.slice(0, 3) : kp.slice(0, 2);
    const summary = `${who} at Florida State University${when} with hands-on experience in ${strengths.length ? strengths.join(", ") : "[your two strongest skills]"}, looking to bring that to the ${jobTitle || "role"} position.`;
    const gaps = gap.missing.slice(0, 6).map(s => ({skill: s, advice: `Only add ${s} if you've really used it, even in a class or club. If not, mention a related skill you do have.`}));
    return {match, skills_present: gap.present, skills_missing: gap.missing, keywords_present: kp, keywords_missing: km.slice(0, 10), lead_bullets: lead, summary, gaps};
  }
  function versioned(resume, summary) {
    const lines = resume.split("\n"); let at = lines.findIndex(l => heading(l)); if (at < 0) at = Math.min(3, lines.length);
    return lines.slice(0, at).concat(["SUMMARY", summary, ""], lines.slice(at)).join("\n");
  }

  // ---------------- feed relevance (feed.py) ----------------
  const FSU_SIGNALS = /\b(?:fsu|florida state|noles?|seminoles?|tallahassee|students?|interns?|internships?|new grads?|recent grads?|entry[- ]level|career fair|career expo|info(?:rmation)? sessions?|on[- ]campus|campus|co-?ops?|graduat\w*|resumes?|interview\w*|mentor\w*|scholarships?|apprentice\w*|part[- ]time|first job|early[- ]career|class of 20\d\d|undergrad\w*|majors?|hiring|job shadow\w*|externships?|fellowships?|networking)\b/gi;
  const PROMO = /\b(?:\d{1,2}\s?% off|discounts?|promo codes?|coupons?|sale ends|buy now|shop now|order now|limited[- ]time offer|free trial|use code|deal of the|giveaway|dm to buy|link in bio|subscribe to|our newsletter|crypto|nft|forex|be your own boss|unlimited income|residual income|financial freedom|passive income|side hustle that pays)\b/gi;
  function relevance(body, kind, link) {
    const text = `${body}\n${link || ""}`;
    const signals = [...new Set(allMatches(FSU_SIGNALS, text).map(m => m[0].toLowerCase()))].sort();
    const promo = [...new Set(allMatches(PROMO, text).map(m => m[0].toLowerCase()))].sort();
    const problems = [];
    if (promo.length) problems.push("It reads like an ad or promotion (" + promo.slice(0, 3).join(", ") + "). The feed is for opportunities and advice, not marketing.");
    if (!signals.length) problems.push("It doesn't say how it helps FSU students. Mention the role, internship, event or advice and who it's for.");
    if (kind === "opportunity" && !/\b(?:apply|application|role|position|job|intern\w*|hiring|opening|deadline|pay|paid|\$\d)/i.test(text)) problems.push("An opportunity post should say what the role is and how to apply.");
    return {ok: !problems.length, signals: signals.slice(0, 6), problems};
  }

  // ---------------- assistant (assistant.py built-in engine) ----------------
  const SCAMQ = /\b(?:scam|legit|real or fake|is this real|fake job|phishing|suspicious|safe to reply)\b/i;
  const RECQ = /\b(?:recommend|suggest|match(?:es|ing)?|fit(?:s)? me|for me|my (?:resume|skills|profile|major)|should i apply|good fit)\b/i;
  const RESQ = /\bresume\b.*\b(?:review|feedback|improve|better|score|fix|help)\b|\b(?:review|improve|fix)\b.*\bresume\b/i;
  const REC_WORDS = new Set(["recommend", "recommendations", "suggest", "suggestions", "match", "matches", "matching", "fit", "fits", "resume", "skills", "profile", "major", "apply", "should", "good", "me?", "resume?", "skills?", "profile?"]);
  const HELLO = /^\s*(?:hi|hey|hello|yo|sup|help|what can you do)\W*$/i;
  function assistant(question, profile, jobs) {
    const q = question.trim();
    if (HELLO.test(q)) return {reply: "Hi! I can find jobs on the board for you, recommend ones that fit your skills and resume, and check whether a message from a 'recruiter' is a scam. Try one of the suggestions below.", jobs: []};
    if (SCAMQ.test(q) && (q.length > 160 || q.includes("\n") || q.includes('"') || q.includes(":"))) {
      const text = q.slice(0, 80).includes(":") ? q.slice(q.indexOf(":") + 1) : q; const r = check(text);
      const reasons = r.findings.slice(0, 4).map(f => "• " + f.title).join("\n") || "• No known scam patterns matched.";
      return {reply: `Verdict: ${r.title}.\n${r.advice}\n\nWhat I found:\n${reasons}\n\nFor the full breakdown and next steps, use Scam check.`, jobs: [], scam: r};
    }
    if (SCAMQ.test(q)) return {reply: "Paste the whole message after a colon, like: “Is this a scam: Hi, I'm Dr. Lee from the Psychology department…”, and I'll check it. You can also use the Scam check page for the full breakdown.", jobs: []};
    if (RESQ.test(q)) {
      if (profile && profile.resume_text) { const rv = review(profile.resume_text); const tips = rv.findings.slice(0, 4).map(f => "• " + f.message).join("\n") || "• It's in good shape.";
        return {reply: `Your resume scores ${rv.score}/100 (${rv.grade}). Top fixes:\n${tips}\n\nOpen Resume studio for line-by-line rewrites and a version tailored to any job.`, jobs: []}; }
      return {reply: "Add your resume in Resume studio and I'll score it, suggest rewrites, and tailor it to any listing.", jobs: []};
    }
    if (!jobs.length) return {reply: "There are no approved listings on the board right now. New ones appear as reviewers approve them. Meanwhile, I can review your resume or check a message for scams.", jobs: []};
    const pq = parseQuery(q), specific = pq.keywords.filter(w => !REC_WORDS.has(w));
    if (RECQ.test(q) && !specific.length && !pq.category && !pq.work_type && !pq.skills.length) {
      if (!profile || !profile.display_name || !profile.major) return {reply: "Set up your profile (skills, interests, resume) and I'll rank jobs for you. Here are the newest listings meanwhile.", jobs: rankJobs(jobs, null, "", 5)};
      const ranked = rankJobs(jobs, profile, "", 6).filter(r => r.score > 0).slice(0, 5);
      const sk = (profile.skills || []).slice(0, 4).join(", ");
      return {reply: `${sk ? `Based on your profile (${sk})` : "Based on your profile"}, these fit you best. Each card says why.`, jobs: ranked};
    }
    const ranked = rankJobs(jobs, profile, q, 5);
    if (ranked.length) return {reply: `Here ${ranked.length === 1 ? "is" : "are"} ${ranked.length} listing${ranked.length !== 1 ? "s" : ""} for “${q.slice(0, 80)}”, best match first.`, jobs: ranked};
    return {reply: `No listing matches “${q.slice(0, 80)}” exactly right now. These are the closest, based on your profile. Try fewer words, or a different job type.`, jobs: rankJobs(jobs, profile, q, 4, false)};
  }

  const NCS = {normalize, runTextRules, scorePosting, check, LEVELS, NEXT_STEPS, extractSkills, normalizeSkill, parseQuery, rankJobs, keywordGap,
    categoriesForMajor, review, improveBullet, bulletIssues, tailor, versioned, relevance, assistant, POPULAR, CATEGORIES, WORK_TYPES, JOB_KINDS, SKILLS,
    ruleset: RULEPACK.version};
  root.NCS = NCS;
  if (typeof module !== "undefined" && module.exports) module.exports = NCS;
})(typeof window !== "undefined" ? window : globalThis);
