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
    const p = profile || {};
    if ((p.skills || []).length || p.resume_text || (p.items || []).length) {
      for (const r of out) { const f = fitScore(r.job, p); r.fit = {score: f.score, label: f.label}; }
      if (!q) out.sort((a, b) => b.fit.score - a.fit.score || b.score - a.score || (b.job.id - a.job.id));
    }
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
  const MYSKILLS = /\b(?:match(?:es|ing)?|fit(?:s|ting)?|suit(?:s|ed)?|for)\b.{0,24}\b(?:my )?(?:skills|resume|profile|major|background)\b|\bjobs? for me\b/i;
  const DRAFTQ = /\b(?:draft|write|build|make|create|start|craft)\b.{0,24}\b(?:resume|cv)\b|\bcover letter\b/i;
  const INTERVIEWQ = /\binterview/i;
  const HELLO = /^\s*(?:hi|hey|hello|yo|sup|help|what can you do)\W*$/i;
  function assistant(question, profile, jobs) {
    const q = question.trim();
    if (HELLO.test(q)) return {reply: "Hi! I can find jobs on the board for you, recommend ones that fit your skills and resume, point you to Resume studio, share interview tips and check whether a message from a 'recruiter' is a scam. Try one of the suggestions below.", jobs: []};
    if (SCAMQ.test(q) && (q.length > 160 || q.includes("\n") || q.includes('"') || q.includes(":"))) {
      const text = q.slice(0, 80).includes(":") ? q.slice(q.indexOf(":") + 1) : q; const r = check(text);
      const reasons = r.findings.slice(0, 4).map(f => "• " + f.title).join("\n") || "• No known scam patterns matched.";
      return {reply: `Verdict: ${r.title}.\n${r.advice}\n\nWhat I found:\n${reasons}\n\nFor the full breakdown and next steps, use Scam check.`, jobs: [], scam: r};
    }
    if (SCAMQ.test(q)) return {reply: "Paste the whole message after a colon, like: “Is this a scam: Hi, I'm Dr. Lee from the Psychology department…”, and I'll check it. You can also use the Scam check page for the full breakdown.", jobs: []};
    if (DRAFTQ.test(q) && !RESQ.test(q)) {
      const have = !!(profile && profile.resume_text);
      return {reply: "Resume studio is where resumes get built here. " + (have ? "Yours is already saved, so you can edit it, score it and tailor a version to any listing." : "Add or paste what you have and it will score it, rewrite weak lines without inventing anything, and tailor it to any listing.") + " I don't write resumes in chat, so I don't put words about you on paper that you didn't say.", jobs: [], handoff: "resume"};
    }
    if (INTERVIEWQ.test(q) && !SCAMQ.test(q)) return {reply: "A simple way to get ready for an interview:\n" +
      "• Read the listing again and note the three things they ask for most. Have one real example from school, work or a project for each.\n" +
      "• Look up the company on its own website and be ready to say why you want this role there.\n" +
      "• Practice a 30-second answer to “Tell me about yourself”: who you are, what you've done, what you want next.\n" +
      "• Prepare a short story for a challenge, a team moment and something you learned (situation, what you did, result).\n" +
      "• Have two questions of your own, such as what the first month looks like.\n" +
      "• Confirm the interview through the employer's own site or email. Real interviews never require you to pay, buy equipment or share bank details.", jobs: [], interview: true};
    if (RESQ.test(q)) {
      if (profile && profile.resume_text) { const rv = review(profile.resume_text); const tips = rv.findings.slice(0, 4).map(f => "• " + f.message).join("\n") || "• It's in good shape.";
        return {reply: `Your resume scores ${rv.score}/100 (${rv.grade}). Top fixes:\n${tips}\n\nOpen Resume studio for line-by-line rewrites and a version tailored to any job.`, jobs: []}; }
      return {reply: "Add your resume in Resume studio and I'll score it, suggest rewrites, and tailor it to any listing.", jobs: []};
    }
    if (!jobs.length) return {reply: "There are no approved listings on the board right now. New ones appear as reviewers approve them. Meanwhile, I can review your resume or check a message for scams.", jobs: []};
    const pq = parseQuery(q), specific = pq.keywords.filter(w => !REC_WORDS.has(w));
    if ((RECQ.test(q) && !specific.length && !pq.category && !pq.work_type && !pq.skills.length) || (MYSKILLS.test(q) && !pq.category && !pq.work_type && !pq.skills.length)) {
      if (!profile || !profile.display_name || !profile.major) return {reply: "Set up your profile (skills, interests, resume) and I'll rank jobs for you. Here are the newest listings meanwhile.", jobs: rankJobs(jobs, null, "", 8)};
      const ranked = rankJobs(jobs, profile, "", 10).filter(r => r.score > 0).slice(0, 8);
      const sk = (profile.skills || []).slice(0, 4).join(", ");
      return {reply: `${sk ? `Based on your profile (${sk})` : "Based on your profile"}, these fit you best. Each card shows how well it matches.`, jobs: ranked};
    }
    const ranked = rankJobs(jobs, profile, q, 8);
    if (ranked.length) return {reply: `Here ${ranked.length === 1 ? "is" : "are"} ${ranked.length} listing${ranked.length !== 1 ? "s" : ""} for “${q.slice(0, 80)}”, best match first.`, jobs: ranked};
    return {reply: `No listing matches “${q.slice(0, 80)}” exactly right now. These are the closest, based on your profile. Try fewer words, or a different job type.`, jobs: rankJobs(jobs, profile, q, 6, false)};
  }

  // ---------- resume -> profile sections (port of resume_parse.py) ----------
  const pyRound = x => { const r = Math.round(x); return (x - Math.floor(x) === 0.5 && r % 2) ? r - 1 : r; };
  const pyTitle = s => (s || "").toLowerCase().replace(/(?<![a-z])[a-z]/g, c => c.toUpperCase());
  const pyStr = x => x === null || x === undefined ? "None" : String(x);
  const sum = a => a.reduce((x, y) => x + y, 0);
  const uniq = a => [...new Set(a)];
  function pyStrip(s, chars) { let a = 0, b = s.length; while (a < b && chars.includes(s[a])) a++; while (b > a && chars.includes(s[b - 1])) b--; return s.slice(a, b); }
  const rpClean = s => pyStrip(s || "", " \t-–—|,·•").replace(/\s+/g, " ").trim();
  const RP_MONTH = "(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|spring|summer|fall|winter|expected)";
  const RP_DATE = `(?:${RP_MONTH}\\.?\\s+)?(?:19|20)\\d{2}|present|current|now`;
  const DATE_RANGE = new RegExp(`(?<start>${RP_DATE})(?:\\s*(?:-|–|—|to)\\s*(?<end>${RP_DATE}))?`, "gi");
  const SCHOOL = /\b(?:university|college|institute|school|academy)\b/i;
  const DEGREE_SRC = "\\b(?:b\\.?s\\.?|b\\.?a\\.?|bachelor(?:'s)?(?: of (?:science|arts))?|m\\.?s\\.?|m\\.?a\\.?|master(?:'s)?(?: of (?:science|arts))?|mba|ph\\.?d|" +
    "associate(?:'s)?(?: of (?:arts|science))?|a\\.?a\\.?|a\\.?s\\.?|high school diploma)\\b";
  const DEGREE = new RegExp(DEGREE_SRC, "i"), DEGREE_AT_START = new RegExp("^(?:" + DEGREE_SRC + ")", "i");
  const GPA_SRC = "\\bgpa\\b[:\\s]*(\\d\\.\\d{1,2})|(\\d\\.\\d{1,2})\\s*(?:/\\s*4\\.0+\\s*)?gpa\\b";
  const RP_GPA = new RegExp(GPA_SRC, "i"), RP_GPA_ALL = new RegExp(GPA_SRC, "gi");
  const RP_SPLIT = /\s+(?:\||–|—|-|·|•|@|at)\s+|,\s+/i;
  const LIST_SPLIT = /[,;|•](?![^()]*\))/;
  const ROLE = /\b(?:intern|analyst|assistant|manager|associate|server|waiter|developer|engineer|generalist|specialist|coordinator|representative|tutor|chair|president|member|volunteer|attendant|advisor|cashier|lead|director|officer|treasurer|secretary|captain|founder|consultant|researcher|clerk|parker|host|barista|teller|designer|writer|editor)\b/i;
  const LABELLED = /^(skills|technical skills|tools|languages|certifications?|licenses?|coursework|relevant coursework|interests)\s*:\s*(.+)$/i;
  const SECTION_KIND = {experience: "experience", leadership: "organization", projects: "project", education: "education", awards: "certification", coursework: "course"};
  const NOW_RX = /^(?:present|current|now)$/i;

  function rpDates(line) {
    let m = null;
    for (const x of line.matchAll(DATE_RANGE)) m = x;
    if (!m) return ["", "", false, line];
    const start = rpClean(m.groups.start); let end = rpClean(m.groups.end || "");
    if (!end && NOW_RX.test(start)) return ["", "", false, line];
    const current = NOW_RX.test(end);
    if (current) end = "";
    let rest = (line.slice(0, m.index) + " " + line.slice(m.index + m[0].length)).trim();
    rest = rest.replace(/(?:^|\s)(?:expected|exp\.?)\s*$/i, "");
    return [/^\d/.test(start) ? start : pyTitle(start), end && !/^\d/.test(end) ? pyTitle(end) : end, current, rest];
  }
  const splitHeader = t => t.split(RP_SPLIT).map(rpClean).filter(Boolean);
  const rpItem = (kind, kw) => Object.assign({kind, title: "", org: "", location: "", start: "", end: "", current: false, description: "", url: "", extra: {}}, kw || {});
  function rpBlocks(lines) {
    const blocks = []; let head = [], body = [];
    for (const ln of lines) {
      if (!ln.trim()) continue;
      if (BULLET.test(ln)) { body.push(ln.replace(BULLET, "").trim()); continue; }
      if (body.length || head.length >= 2) { blocks.push([head, body]); head = []; body = []; }
      head.push(ln.trim());
    }
    if (head.length || body.length) blocks.push([head, body]);
    return blocks;
  }
  function rpEntry(kind, head, body) {
    let start = "", end = "", current = false; const texts = [];
    for (const h of head) { const [s, e, c, rest] = rpDates(h); if (s && !start) { start = s; end = e; current = c; } texts.push(rest); }
    const parts = texts.flatMap(splitHeader);
    if (!parts.length && !body.length) return null;
    let ttl = parts[0] || "", org = parts[1] || "", location = "";
    for (const p of parts.slice(2)) if (/\b[A-Z][a-z]+,?\s+(?:[A-Z]{2}|Florida)\b/.test(p) || /^(?:remote|hybrid|on-?site)$/i.test(p)) { location = p; break; }
    if (location === "" && parts.length > 3 && /^[A-Z]{2}$/.test(parts[parts.length - 1])) location = `${parts[parts.length - 2]}, ${parts[parts.length - 1]}`;
    if (org && ROLE.test(org) && !ROLE.test(ttl)) [ttl, org] = [org, ttl];
    return rpItem(kind, {title: ttl.slice(0, 120), org: org.slice(0, 120), location: location.slice(0, 80), start, end, current,
                         description: body.map(b => "• " + b).join("\n").slice(0, 1500)});
  }
  function rpEducation(lines) {
    const out = []; let cur = null;
    for (const ln of lines) {
      let s = ln.trim(); if (!s) continue;
      s = s.replace(BULLET, "").trim();
      const m = LABELLED.exec(s);
      if (m && m[1].toLowerCase().includes("course")) {
        if (cur !== null) cur.extra.coursework = m[2].split(/[,;]/).map(rpClean).filter(Boolean).slice(0, 20);
        continue;
      }
      const [start, end, current, rest] = rpDates(s);
      const g = RP_GPA.exec(s), parts = splitHeader(rest);
      if (parts.length && SCHOOL.test(parts[0]) && !DEGREE_AT_START.test(parts[0])) {
        cur = rpItem("education"); cur.org = parts[0].slice(0, 120);
        const others = parts.slice(1).filter(p => !RP_GPA.test(p));
        const deg = others.find(p => DEGREE.test(p)) || "";
        if (deg) cur.title = deg.slice(0, 120);
        const loc = others.filter(p => p !== deg && !DEGREE.test(p) && !/minor|expected|coursework/i.test(p));
        if (loc.length && /^[A-Z][A-Za-z .]+$/.test(loc[0]) && loc[0].length < 40) cur.location = loc.slice(0, 2).join(", ").slice(0, 80);
        out.push(cur);
      } else if (cur === null) { cur = rpItem("education"); out.push(cur); }
      if (DEGREE.test(rest) && !cur.title) {
        const dp = splitHeader(rest).find(p => DEGREE.test(p));
        cur.title = rpClean((dp !== undefined ? dp : rest).replace(RP_GPA_ALL, "")).slice(0, 120);
      }
      if (cur.title) {
        const mm = /\b(?:in|of)\s+([A-Z][A-Za-z&\/ ]{2,60}?)(?=,|\.|;|$| (?:minor|Minor|MINOR)| with| (?:expected|Expected)| (?:gpa|GPA))/.exec(cur.title)
          || /^(?:b\.?s\.?|b\.?a\.?|m\.?s\.?|m\.?a\.?|a\.?a\.?|a\.?s\.?|mba)\s+([A-Z][A-Za-z&\/ ]{2,60}?)(?=,|\.|;|$)/i.exec(cur.title);
        if (mm && !cur.extra.major && !/^(?:science|arts)$/i.test(mm[1].trim())) cur.extra.major = rpClean(mm[1]);
      }
      const mn = /\b(?:minor|Minor|MINOR)(?:\s+in)?\s+([A-Z][A-Za-z&\/ ]{2,40}?)(?=[.,;]|$)/.exec(s);
      if (mn) cur.extra.minor = rpClean(mn[1]);
      if (g) cur.extra.gpa = g[1] || g[2];
      if (start && !(cur.start || cur.end)) {
        if (end || current) { cur.start = start; cur.end = end; cur.current = current; }
        else cur.end = start;
      }
    }
    return out.filter(e => e.org || e.title);
  }
  function toProfile(text) {
    const p = parse(text), lines = p.lines;
    const heads = Object.entries(p.sections).map(([k, i]) => [i, k]).sort((a, b) => a[0] - b[0]);
    const items = [], skills = [], languages = [], certs = [];
    const vals = s => s.split(LIST_SPLIT).map(rpClean).filter(Boolean);
    heads.forEach(([startLine, key], n) => {
      const body = lines.slice(startLine + 1, n + 1 < heads.length ? heads[n + 1][0] : lines.length);
      const headingText = lines[startLine].trim().toLowerCase();
      if (key === "education") { items.push(...rpEducation(body)); return; }
      if (key === "skills" || key === "summary" || (key === "awards" && !headingText.includes("cert") && !headingText.includes("licen"))) {
        for (const ln of body) {
          const s = ln.trim().replace(BULLET, "").trim(), m = LABELLED.exec(s);
          if (m) {
            const label = m[1].toLowerCase(), v = vals(m[2]);
            if (label.startsWith("language")) languages.push(...v);
            else if (label.startsWith("cert") || label.startsWith("licen")) certs.push(...v);
            else if (label.includes("course")) items.push(...v.map(x => rpItem("course", {title: x.slice(0, 120)})));
            else skills.push(...v);
          } else if (key === "skills" && s) skills.push(...vals(s));
        }
        return;
      }
      if (key === "awards") {
        for (const ln of body) {
          const s = ln.trim().replace(BULLET, "").trim(); if (!s) continue;
          const [st, en, , rest] = rpDates(s), parts = splitHeader(rest);
          if (parts.length) items.push(rpItem("certification", {title: parts[0].slice(0, 120), org: (parts[1] || "").slice(0, 120), start: st || en}));
        }
        return;
      }
      if (key === "coursework") { for (const ln of body) items.push(...vals(ln.replace(BULLET, "")).map(x => rpItem("course", {title: x.slice(0, 120)}))); return; }
      let kind = SECTION_KIND[key]; if (!kind) return;
      if (kind === "project" && headingText.startsWith("research")) kind = "experience";
      for (const [head, bullets] of rpBlocks(body)) { const e = rpEntry(kind, head, bullets); if (e && (e.title || e.description)) items.push(e); }
    });
    items.push(...certs.map(c => rpItem("certification", {title: c.slice(0, 120)})));
    items.push(...languages.filter(l => !/python|java|sql|html|css|javascript|c\+\+|\br\b/i.test(l)).map(l => rpItem("language", {title: l.slice(0, 60)})));
    const canon = [];
    for (const s of skills.concat(extractSkills(text))) { const c = s.length <= 40 ? s : ""; if (c && !canon.some(x => x.toLowerCase() === c.toLowerCase())) canon.push(c); }
    return {skills: canon.slice(0, 40), items: items.slice(0, 40)};
  }

  // ---------- whole-profile fit score (port of fit.py) ----------
  const FIT_WEIGHTS = {skills: 35, experience: 25, education: 15, certifications: 10, keywords: 10, preferences: 10};
  const FIT_NAMES = {skills: "Skills", experience: "Experience & projects", education: "Education", certifications: "Certifications", keywords: "Keywords", preferences: "Preferences"};
  const PREFERRED = /\b(?:preferred|nice to have|a plus|bonus|ideally|desired|is helpful|are helpful|not required|familiarity with)\b/i;
  const SENT_RX = /[^.\n;!?]+[.\n;!?]?/g;
  const MAJORS = {
    "accounting": ["accounting"], "finance": ["finance"], "economics": ["economics"], "business": ["business administration", "business"],
    "marketing": ["marketing"], "management": ["management"], "statistics": ["statistics"], "mathematics": ["mathematics", "math"],
    "computer science": ["computer science", "cs"], "information technology": ["information technology", "information systems", "mis"],
    "data science": ["data science", "analytics"], "engineering": ["engineering"], "biology": ["biology", "biological"],
    "chemistry": ["chemistry"], "psychology": ["psychology"], "communications": ["communications", "communication", "media"],
    "journalism": ["journalism"], "public health": ["public health"], "nursing": ["nursing"], "education": ["education"],
    "english": ["english"], "political science": ["political science"], "criminology": ["criminology", "criminal justice"],
    "hospitality": ["hospitality"], "supply chain": ["supply chain"], "real estate": ["real estate"], "graphic design": ["graphic design", "design"],
    "sociology": ["sociology"], "physics": ["physics"], "neuroscience": ["neuroscience"], "nutrition": ["nutrition"],
    "exercise science": ["exercise science", "kinesiology"], "social work": ["social work"],
  };
  const MAJOR_CONTEXT = /\b(?:major(?:s|ing)?|degree|studying|pursuing|coursework|background|students?|enrolled in)\b/i;
  const NOT_MAJOR = {business: "business(?!\\s+(?:analytics|intelligence|development|hours|days|casual|needs|partners?|owners?))",
                     analytics: "analytics", communication: "communication(?!\\s+skills)", design: "design"};
  const MAJOR_RX = {}; for (const ws of Object.values(MAJORS)) for (const w of ws) MAJOR_RX[w] = new RegExp("\\b" + (NOT_MAJOR[w] || reEsc(w)) + "\\b");
  const TERM_STOP = new Set([...GENERIC, ...`build building built help helping clean cleaning present presenting weekly daily monthly hours hour week
paid pay team teams short friday readout support supporting assist assisting including include includes must should will
would also please apply summer fall spring semester during per plus related field fields minimum required requirements preferred
role roles position candidate strong comfort comfortable ability experience experienced familiarity knowledge work working job jobs
student students intern interns internship years year ideal responsibilities responsible opportunity join grow growing learn
learning great good using used flag find make ensure provide biweekly juniors seniors sophomores freshmen freshman junior senior
majoring major majors minor degree hold holds certified certification certifications preferably`.split(/\s+/), ...Object.values(MAJORS).flat()]);
  const STANDING = /\b(freshm[ae]n|sophomores?|juniors?|seniors?|graduate students?|recent grad(?:uate)?s?|new grads?)\b/gi;
  const GRAD_YEAR = /\b(?:graduating|graduation|class of|grad date)\D{0,24}((?:19|20)\d{2})\b/gi;
  const GPA_REQ = /\b(?:gpa|grade point average)\D{0,30}?(\d\.\d{1,2})|(\d\.\d{1,2})\s*(?:\+|or (?:higher|above|better))?\s*(?:cumulative\s+|minimum\s+)?gpa\b/i;
  const CERTS = {
    "CPR/First aid": "\\bcpr\\b|\\bfirst aid\\b|\\bbls\\b", "ServSafe / food handler": "\\bservsafe\\b|\\bfood handler",
    "CompTIA": "\\bcomptia\\b|\\ba\\+ certif|\\bsecurity\\+|\\bnetwork\\+", "Microsoft Office Specialist": "\\bmicrosoft office specialist\\b|\\bmos certif|\\bexcel (?:expert|certif)",
    "Google Analytics certification": "\\bgoogle analytics (?:certif|individual)|\\bga4 certif", "CNA": "\\bcna\\b|\\bcertified nursing assistant\\b",
    "EMT": "\\bemt\\b", "Lifeguard": "\\blifeguard", "Driver's license": "\\bdriver'?s licen[cs]e\\b|\\bvalid (?:driver'?s )?licen[cs]e\\b",
    "AWS certification": "\\baws certif|\\baws certified\\b", "SHRM": "\\bshrm\\b", "Notary": "\\bnotary\\b",
    "Bloomberg (BMC)": "\\bbloomberg market concepts\\b|\\bbmc\\b", "Tableau certification": "\\btableau (?:desktop )?(?:specialist|certif)",
    "HIPAA training": "\\bhipaa (?:training|certif)", "Salesforce certification": "\\bsalesforce (?:certif|administrator|trailhead)",
  };
  const CERTS_RX = {}; for (const [k, v] of Object.entries(CERTS)) CERTS_RX[k] = new RegExp(v, "i");
  const TITLE_STOP = new Set("intern internship part time part-time full full-time assistant associate student entry level junior senior the and of for".split(" "));
  const FIT_LABELS = [[80, "Strong fit"], [65, "Good fit"], [45, "Partial fit"], [0, "Stretch"]];
  const KIND_TEXT = {"internship": [" intern", "internship", "co-op"], "part-time": ["part-time", "part time"], "full-time": ["full-time", "full time"], "on-campus": ["on campus", "on-campus"]};
  const wordRx = t => new RegExp("(?<![a-z0-9])" + reEsc(t) + "(?![a-z0-9])");

  function fitTerms(text, n) {
    const counts = new Map();
    for (const w of ((text || "").toLowerCase().match(/[a-z][a-z\-]{3,}/g) || [])) if (!TERM_STOP.has(w) && !w.endsWith("ly")) counts.set(w, (counts.get(w) || 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1]).map(e => e[0]).slice(0, n || 10);
  }
  function jobRequirements(ttl, text) {
    const full = `${ttl}\n${text}`, sents = [...full.matchAll(SENT_RX)].map(m => m[0]);
    let required = [], preferred = [];
    for (const sent of sents) for (const s of extractSkills(sent)) (PREFERRED.test(sent) ? preferred : required).push(s);
    required = uniq(required); preferred = uniq(preferred).filter(s => !required.includes(s));
    const majors = [];
    for (const sent of sents) if (MAJOR_CONTEXT.test(sent)) {
      const low = " " + sent.toLowerCase() + " ";
      for (const [canon, words] of Object.entries(MAJORS)) if (words.some(w => MAJOR_RX[w].test(low)) && !majors.includes(canon)) majors.push(canon);
    }
    const g = GPA_REQ.exec(full), gpa = g ? parseFloat(g[1] || g[2]) : null;
    let standing = uniq([...full.matchAll(STANDING)].map(m => m[1].toLowerCase().replace(/s+$/, "").replaceAll("freshmen", "freshman").replaceAll("freshme", "freshman"))).sort();
    standing = uniq(standing.map(s => /^(?:graduate|recent|new)/.test(s) ? "graduate" : s)).sort();
    const gy = uniq([...full.matchAll(GRAD_YEAR)].map(m => parseInt(m[1], 10))).sort((a, b) => a - b);
    const certs = Object.keys(CERTS).filter(k => CERTS_RX[k].test(full));
    required = required.filter(s => !certs.includes(s)); preferred = preferred.filter(s => !certs.includes(s));
    const low = " " + full.toLowerCase() + " ";
    const kind = JOB_KINDS.find(k => KIND_TEXT[k].some(w => low.includes(w))) || "";
    const sk = new Set(required.concat(preferred).map(s => s.toLowerCase()));
    return {required, preferred, majors, gpa, standing, grad_years: gy, certs, kind, keywords: fitTerms(full).filter(k => !sk.has(k))};
  }
  function fitGradYear(p) {
    const m = /((?:19|20)\d{2})/.exec(p.grad_term || ""); if (m) return parseInt(m[1], 10);
    for (const it of p.items || []) if (it.kind === "education" && !it.current && it.end) { const y = /((?:19|20)\d{2})/.exec(it.end); if (y) return parseInt(y[1], 10); }
    return null;
  }
  function fitStanding(gy, today) {
    if (!gy) return "";
    const left = gy - today[0] - (today[1] >= 7 ? 0.5 : 0);
    return left < 0 ? "graduate" : left <= 1 ? "senior" : left <= 2 ? "junior" : left <= 3 ? "sophomore" : "freshman";
  }
  function fitSources(p) {
    const out = [];
    if ((p.skills || []).length) out.push(["Your skills list", "skills", p.skills.join(", ")]);
    for (const it of p.items || []) {
      const k = it.kind, ex = it.extra || {};
      const text = [it.title, it.org, it.description, (ex.coursework || []).join(" "), ex.major || "", ex.skills || ""].map(pyStr).join(" ");
      const name = it.title || it.org || k;
      const labels = {experience: name + (it.org && it.title ? ` at ${it.org}` : ""), project: `${name} (project)`, education: it.org || name,
                      certification: `${name} (certification)`, organization: it.org || name, course: `${name} (course)`, language: name};
      out.push([Object.prototype.hasOwnProperty.call(labels, k) ? labels[k] : name, k, text]);
    }
    if (p.resume_text) out.push(["Your resume", "resume", p.resume_text]);
    const about = [p.headline, p.bio].filter(Boolean).join(" ");
    if (about) out.push(["Your headline and about", "about", about]);
    return out;
  }
  function fitGpa(p) {
    for (const it of p.items || []) { const g = (it.extra || {}).gpa; if (g) { const f = Number(g); if (String(g).trim() && !isNaN(f)) return f; } }
    const m = RP_GPA.exec(p.resume_text || "");
    return m ? parseFloat(m[1] || m[2]) : null;
  }
  function jobCategories(job) {
    const out = job.category ? [job.category] : [], low = " " + ((job.title || "") + " " + (job.description || "")).toLowerCase() + " ";
    for (const [cat, words] of Object.entries(CATEGORY_WORDS)) if (!out.includes(cat) && words.filter(w => low.includes(w)).length >= 2) out.push(cat);
    return out;
  }
  function fitScore(job, profile, today) {
    profile = profile || {};
    if (!today) { const d = new Date(); today = [d.getUTCFullYear(), d.getUTCMonth() + 1]; }
    let req = jobRequirements(job.title || "", job.description || "");
    const chosen = qualsOf(job), mustOf = {};
    if (chosen.length) req = mergeQuals(req, chosen, mustOf);
    const srcs = fitSources(profile), items = profile.items || [];
    const where = new Map();
    for (const [label, , text] of srcs) for (const s of extractSkills(text)) { if (!where.has(s)) where.set(s, []); where.get(s).push(label); }
    for (const s of profile.skills || []) { const cur = where.get(s) || []; if (!cur.includes("Your skills list")) { where.set(s, cur); cur.unshift("Your skills list"); } }
    const allText = srcs.map(x => x[2]).join(" ").toLowerCase();
    for (const q of chosen) if (q.kind === "skill" && !where.has(q.label)) {
      const rx = new RegExp("(?<![a-z0-9])" + q.label.toLowerCase().replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "(?![a-z0-9])");
      const hits = srcs.filter(x => rx.test(x[2].toLowerCase())).map(x => x[0]);
      if (hits.length) where.set(q.label, hits);
    }
    const parts = {}, checklist = [];

    const wanted = req.required.map(s => [s, 1.0, true]).concat(req.preferred.map(s => [s, 0.5, false]));
    const matched = [], missing = [];
    if (wanted.length) {
      const got = sum(wanted.filter(w => where.has(w[0])).map(w => w[1])), total = sum(wanted.map(w => w[1]));
      for (const [s, , isReq] of wanted) {
        if (where.has(s)) matched.push({skill: s, required: isReq, where: uniq(where.get(s)).slice(0, 3)});
        else missing.push({skill: s, required: isReq});
        checklist.push({text: s + (isReq ? "" : " (preferred)"), status: where.has(s) ? "met" : "missing", evidence: uniq(where.get(s) || []).slice(0, 2).join(", ")});
      }
      parts.skills = {score: pyRound(100 * got / total), detail: `${matched.length} of ${wanted.length} skills the job lists` +
        (req.required.length && req.preferred.length ? ` (${matched.filter(m => m.required).length} of ${req.required.length} required)` : "")};
    }

    const terms = req.required.concat(req.preferred).map(s => s.toLowerCase()).concat(req.keywords.slice(0, 8));
    let entries = srcs.filter(x => ["experience", "project", "organization"].includes(x[1])).map(x => [x[0], x[2].toLowerCase()]);
    if (!entries.length && profile.resume_text) entries = parse(profile.resume_text).bullets.map(b => ["Your resume", b.text.toLowerCase()]);
    const relevant = [];
    if (entries.length && terms.length) {
      const covered = new Set();
      for (const [label, text] of entries) {
        const has = new Set(extractSkills(text).map(x => x.toLowerCase()));
        const hits = terms.filter(t => has.has(t) || wordRx(t).test(text));
        if (hits.length) { relevant.push({where: label, hits: hits.slice(0, 4)}); hits.forEach(h => covered.add(h)); }
      }
      const coverage = Math.min(1, covered.size / Math.max(3, pyRound(terms.length * 0.6)));
      const twords = ((job.title || "").toLowerCase().match(/[a-z]+/g) || []).filter(w => !TITLE_STOP.has(w) && w.length > 2);
      const role = twords.length ? entries.some(([, text]) => twords.some(w => text.slice(0, 120).includes(w))) : false;
      parts.experience = {score: pyRound(100 * (0.75 * coverage + 0.25 * (role ? 1 : 0))),
        detail: (relevant.length ? `${relevant.length} of your entries relate to this job` : "None of your entries mention what this job asks for yet") + (role ? "; you've held a similar role" : "")};
    } else if (terms.length) parts.experience = {score: 0, detail: "Add your experience and projects so they can count"};

    const eduScores = [], eduNotes = [];
    const myMajors = [profile.major || "", profile.minor || ""]
      .concat(items.filter(it => it.kind === "education").map(it => { const ex = it.extra || {}; return (ex.major || "") + " " + (ex.minor || "") + " " + (it.title || "") + " " + (ex.coursework || []).join(" "); }))
      .concat(items.filter(it => it.kind === "course").map(it => it.title || "")).join(" ").toLowerCase();
    if (req.majors.length) {
      const hit = req.majors.filter(m => MAJORS[m].some(w => MAJOR_RX[w].test(myMajors)));
      if (hit.length) { eduScores.push(1.0); eduNotes.push("Your major or coursework covers " + hit.slice(0, 2).join(" and ")); }
      else if (/related field|similar field|or related|quantitative field/i.test(job.description || "") && categoriesForMajor(profile.major || "").some(c => jobCategories(job).includes(c))) {
        eduScores.push(0.6); eduNotes.push("Your major is related to the fields they list");
      } else { eduScores.push(myMajors.trim() ? 0.15 : 0.4); eduNotes.push("They list " + req.majors.slice(0, 3).join(", ") + " majors"); }
      checklist.push({text: "Major: " + req.majors.slice(0, 4).join(" or "), status: hit.length ? "met" : (!myMajors.trim() ? "unknown" : "missing"), evidence: profile.major || ""});
    } else if (profile.major) {
      const fits = categoriesForMajor(profile.major).some(c => jobCategories(job).includes(c));
      eduScores.push(fits ? 0.9 : 0.65); eduNotes.push(fits ? "Your major lines up with this kind of work" : "No specific major required");
    }
    if (req.gpa) {
      const have = fitGpa(profile); let status;
      if (have === null) { eduScores.push(0.6); status = "unknown"; eduNotes.push(`Asks for a ${req.gpa.toFixed(1)}+ GPA; add yours if you meet it`); }
      else { const ok = have >= req.gpa - 1e-9; eduScores.push(ok ? 1.0 : 0.1); status = ok ? "met" : "missing"; eduNotes.push(`GPA ${have.toFixed(2)} vs ${req.gpa.toFixed(1)} required`); }
      checklist.push({text: `GPA ${req.gpa.toFixed(1)} or higher`, status, evidence: have === null ? "" : have.toFixed(2)});
    }
    const gy = fitGradYear(profile), standing = fitStanding(gy, today);
    if (req.standing.length || req.grad_years.length) {
      let ok = null;
      if (req.grad_years.length && gy) ok = req.grad_years.includes(gy);
      else if (req.standing.length && standing) ok = req.standing.includes(standing);
      const want = req.standing.map(s => s.endsWith("e") ? pyTitle(s) + " students" : pyTitle(s) + "s").concat(req.grad_years.map(String)).join(", ");
      eduScores.push(ok === null ? 0.6 : (ok ? 1.0 : 0.2));
      checklist.push({text: "Class standing: " + want, status: ok === null ? "unknown" : (ok ? "met" : "missing"), evidence: (standing ? pyTitle(standing) : "") + (gy ? `, graduating ${gy}` : "")});
      eduNotes.push(`They want ${want}` + (standing ? `; you're a ${standing}` : ""));
    }
    if (eduScores.length) parts.education = {score: pyRound(100 * sum(eduScores) / eduScores.length), detail: eduNotes.slice(0, 2).join("; ")};

    if (req.certs.length) {
      const have = req.certs.filter(c => (CERTS_RX[c] || new RegExp("(?<![a-z0-9])" + c.toLowerCase().replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "(?![a-z0-9])", "i")).test(allText));
      parts.certifications = {score: pyRound(100 * have.length / req.certs.length), detail: `${have.length} of ${req.certs.length}: ` + req.certs.slice(0, 3).join(", ")};
      for (const c of req.certs) checklist.push({text: c, status: have.includes(c) ? "met" : "missing", evidence: ""});
    }

    let kwHit = [];
    if (req.keywords.length) {
      kwHit = req.keywords.filter(k => wordRx(k).test(allText));
      parts.keywords = {score: pyRound(100 * kwHit.length / req.keywords.length), detail: `${kwHit.length} of ${req.keywords.length} key terms from the posting`};
    }

    const prefs = [], pnotes = [], wt = job.work_type || "";
    if ((profile.work_types || []).length) { const ok = profile.work_types.includes(wt); prefs.push(ok ? 1.0 : 0.3); pnotes.push(wt.charAt(0).toUpperCase() + wt.slice(1) + (ok ? " matches what you want" : " isn't your first choice")); }
    if (req.kind && (profile.job_kinds || []).length) { const ok = profile.job_kinds.includes(req.kind); prefs.push(ok ? 1.0 : 0.3); pnotes.push(req.kind.charAt(0).toUpperCase() + req.kind.slice(1) + (ok ? " is a type you want" : " isn't a type you picked")); }
    const locs = (profile.pref_locations || []).filter(Boolean).map(l => l.toLowerCase());
    if (locs.length && wt !== "remote" && job.location) {
      const jl = job.location.toLowerCase();
      const ok = locs.some(l => jl.includes(l.split(",")[0].trim()) || l.includes(jl.split(",")[0].trim()));
      prefs.push(ok ? 1.0 : 0.4); pnotes.push((ok ? "In " : "Outside ") + "your preferred locations");
    }
    if (prefs.length) parts.preferences = {score: pyRound(100 * sum(prefs) / prefs.length), detail: pnotes.slice(0, 2).join("; ")};

    const keys = Object.keys(FIT_WEIGHTS).filter(k => parts[k]);
    const totalW = sum(keys.map(k => FIT_WEIGHTS[k]));
    const score = totalW ? pyRound(sum(keys.map(k => FIT_WEIGHTS[k] * parts[k].score)) / totalW) : 0;
    const completeness = [(profile.skills || []).length, profile.resume_text, items.some(i => i.kind === "experience" || i.kind === "project"), profile.major].filter(Boolean).length;
    return {score, label: FIT_LABELS.find(([cut]) => score >= cut)[1], confidence: ["low", "low", "medium", "medium", "high"][completeness],
            parts: keys.map(k => Object.assign({key: k, name: FIT_NAMES[k], weight: FIT_WEIGHTS[k]}, parts[k])), matched, missing, relevant: relevant.slice(0, 5),
            keywords_hit: kwHit, keywords_missing: req.keywords.filter(k => !kwHit.includes(k)).slice(0, 8), checklist: checklist.slice(0, 16).map(c => Object.assign({}, c, {must: isMust(c.text, mustOf)})), requirements: req,
            percent: score, level: score >= 75 ? "high" : (score >= 50 ? "medium" : "low"), met: checklist.filter(c => c.status === "met").length, total: checklist.length};
  }
  const QUAL_KINDS = {skill: "Skill", major: "Major", cert: "Certification", standing: "Class standing", gradyear: "Graduation year", gpa: "Minimum GPA"};
  function qualsOf(job) {
    let raw = job.requirements;
    if (typeof raw === "string") { try { raw = JSON.parse(raw || "[]"); } catch (e) { raw = []; } }
    return (raw || []).filter(q => q && QUAL_KINDS[q.kind] && q.label);
  }
  function mergeQuals(req0, chosen, mustOf) {
    const req = JSON.parse(JSON.stringify(req0));
    for (const q of chosen) {
      const k = q.kind, l = q.label;
      mustOf[l.toLowerCase()] = !!q.must;
      if (k === "skill") {
        const [bucket, other] = q.must ? ["required", "preferred"] : ["preferred", "required"];
        if (req[other].includes(l)) req[other] = req[other].filter(x => x !== l);
        if (!req[bucket].includes(l) && !req.required.includes(l)) req[bucket].push(l);
      } else if (k === "major") {
        const canon = Object.keys(MAJORS).find(c => l.toLowerCase() === c.toLowerCase() || MAJORS[c].includes(l.toLowerCase())) || l;
        if (!req.majors.includes(canon)) req.majors.push(canon);
      } else if (k === "cert") {
        if (!req.certs.includes(l)) req.certs.push(l);
        req.required = req.required.filter(x => x !== l);
      } else if (k === "standing") req.standing = [...new Set(req.standing.concat([l]))].sort();
      else if (k === "gradyear") req.grad_years = [...new Set(req.grad_years.concat([parseInt(l, 10)]))].sort((a, b) => a - b);
      else if (k === "gpa") req.gpa = parseFloat(l);
    }
    return req;
  }
  function isMust(text, mustOf) {
    const t = text.toLowerCase().replace(" (preferred)", "");
    for (const k of [t, t.split(":").slice(-1)[0].trim()]) if (k in mustOf) return mustOf[k];
    return Object.keys(mustOf).some(m => mustOf[m] && t.includes(m));
  }

  // ---------- employer trust score (port of employer_page.trust_from_signals) ----------
  const T_WEIGHTS = {verification: 30, listings: 25, conduct: 20, responsiveness: 15, profile: 10};
  const T_NAMES = {verification: "Verification", listings: "Listing record", conduct: "Conduct with students", responsiveness: "Responsiveness", profile: "Profile"};
  const T_LABELS = [[85, "Highly trusted", "ok"], [70, "Trusted", "ok"], [50, "Building trust", ""], [0, "Use caution", "bad"]];
  const PROFILE_FIELDS = [["website", "a website"], ["about", "an About section"], ["industry", "your industry"], ["size", "company size"], ["location", "a location"],
    ["contact_name", "a contact name"], ["fsu_connection", "how you work with FSU students"], ["tagline", "a tagline"], ["linkedin", "your LinkedIn page"],
    ["founded", "the year you were founded"], ["hires_for", "the kinds of roles you hire for"], ["perks", "your perks"]];
  const tPct = x => Math.max(0, Math.min(100, pyRound(100 * x)));
  const median = a => !a.length ? null : a.length % 2 ? a[(a.length - 1) / 2] : (a[a.length / 2 - 1] + a[a.length / 2]) / 2;
  function replyTime(h) { if (h === null || h === undefined) return ""; if (h < 1) return "an hour"; if (h < 24) return `${Math.floor(h) + 1} hours`; const d = Math.floor(h / 24) + (h % 24 ? 1 : 0); return `${d} day${d !== 1 ? "s" : ""}`; }
  function trustFromSignals(s) {
    const parts = {}, tips = [];
    const approval = {approved: 1, pending: 0.35}[s.status] || 0, dom = {match: 1, other: 0.6, free: 0.2}[s.domain];
    const age = s.days_approved >= 180 ? 1 : s.days_approved >= 30 ? 0.8 : approval === 1 ? 0.6 : 0.3;
    parts.verification = [tPct(0.6 * approval + 0.25 * dom + 0.15 * age), [{approved: "Approved by a NoleCareerShield reviewer", pending: "Waiting for a reviewer"}[s.status] || "Not approved",
      {match: "email matches their website", other: "email domain differs from their website", free: "uses a personal email address"}[s.domain]].join("; ")];
    if (s.domain === "free") tips.push("Sign up with an email on your company's domain instead of a personal address.");
    if (s.listings) {
      let base = 0.6 * s.approved / s.listings + 0.4 * s.clear / s.listings;
      if (s.leadgen_rejections) base -= 0.25; if (s.scam_rejections) base = Math.min(base, 0.1);
      parts.listings = [tPct(base), `${s.approved} of ${s.listings} listings approved` + (s.scam_rejections ? `; ${s.scam_rejections} rejected as a scam` : "") + (s.leadgen_rejections ? `; ${s.leadgen_rejections} rejected as an aggregator` : "")];
    } else { parts.listings = [60, "No listings reviewed yet"]; tips.push("Post a listing. Each approved listing builds your record."); }
    const bad = [s.held && `${s.held} message${s.held !== 1 ? "s" : ""} held by the scam scanner`, s.flagged && `${s.flagged} flagged`, s.cautioned && `${s.cautioned} with warning signs`,
      s.reports && `${s.reports} open report${s.reports !== 1 ? "s" : ""} from students`, s.blocks && `blocked by ${s.blocks} student${s.blocks !== 1 ? "s" : ""}`].filter(Boolean);
    parts.conduct = [tPct(1 - 0.35 * s.held - 0.2 * s.flagged - 0.1 * s.cautioned - 0.3 * s.reports - 0.15 * s.blocks), bad.length ? bad.join("; ") : s.sent ? "No scanner flags, reports or blocks" : "No messages sent yet"];
    if (s.threads) {
      const rate = s.replied / s.threads, med = median(s.reply_hours), speed = med === null ? 0 : med <= 24 ? 1 : med <= 72 ? 0.7 : med <= 168 ? 0.4 : 0.1;
      parts.responsiveness = [tPct(0.6 * rate + 0.4 * speed), `Answered ${s.replied} of ${s.threads} student messages` + (med !== null ? `; usually within ${replyTime(med)}` : "")];
      if (rate < 0.8) tips.push("Answer every student who messages you, even with a quick no.");
    } else parts.responsiveness = [60, "No student messages yet"];
    const has = k => { const v = s.profile[k]; return Array.isArray(v) ? v.length > 0 : !!v && (k !== "about" || v.length >= 40); };
    const have = PROFILE_FIELDS.filter(([k]) => has(k));
    parts.profile = [tPct(have.length / PROFILE_FIELDS.length), `${have.length} of ${PROFILE_FIELDS.length} details filled in`];
    const missing = PROFILE_FIELDS.filter(([k]) => !has(k)).map(x => x[1]);
    if (missing.length) tips.push("Add " + missing.slice(0, 3).join(", ") + " to your company profile.");
    let score = pyRound(Object.keys(T_WEIGHTS).reduce((a, k) => a + T_WEIGHTS[k] * parts[k][0], 0) / 100);
    if (s.status !== "approved") score = Math.min(score, 49);
    if (s.scam_rejections) score = Math.min(score, 30);
  if (s.reports || s.flagged) score = Math.min(score, 69);
  if (s.held) score = Math.min(score, 49);
    const [, label, tone] = T_LABELS.find(([cut]) => score >= cut);
    return {score, label, tone, new: !(s.listings || s.threads), parts: Object.keys(T_WEIGHTS).map(k => ({key: k, name: T_NAMES[k], weight: T_WEIGHTS[k], score: parts[k][0], detail: parts[k][1]})), tips: tips.slice(0, 4)};
  }

  // ---- optimizer report (mirrors resume_engine.report / add_skills / stand_out) ----
  const REPORT_SECTIONS = [["formatting", "Formatting", 35], ["keywords", "Keywords", 20], ["impact", "Impact & bullets", 45], ["contact", "Contact & structure", 20]];
  const FIND_SECTION = [[/^Only \d+ of|strong verb|same verb/, "impact"], [/^No email|^No phone|LinkedIn|Education|graduation|Experience, Projects/, "contact"], [/Skills section/, "keywords"]];
  const findingSection = msg => { for (const [rx, k] of FIND_SECTION) if (rx.test(msg)) return k; return "formatting"; };
  const hasWord = (low, term) => new RegExp("(?<![a-z0-9])" + term.toLowerCase().replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "(?![a-z0-9])").test(low);
  function missingProfileSkills(text, skills) {
    const low = (text || "").toLowerCase(), out = [];
    for (let s of skills || []) { s = String(s).trim(); if (s && s.length <= 40 && !hasWord(low, s) && !out.some(o => o.toLowerCase() === s.toLowerCase())) out.push(s); }
    return out.slice(0, 12);
  }
  function addSkills(text, skills) {
    skills = missingProfileSkills(text, skills); if (!skills.length) return text;
    const lines = (text || "").split(/\r?\n/), at = parse(text).sections.skills; if (lines.length && lines[lines.length - 1] === "") lines.pop();
    if (at === undefined) return (text || "").replace(/\n+$/, "") + "\n\nSKILLS\n" + skills.join(", ") + "\n";
    let j = at + 1; while (j < lines.length && !lines[j].trim()) j++;
    if (j >= lines.length || heading(lines[j])) lines.splice(at + 1, 0, skills.join(", "));
    else lines[j] = lines[j].replace(/\s+$/, "").replace(/[,;]+$/, "") + ", " + skills.join(", ");
    return lines.join("\n");
  }
  function setSummary(text, summary) {
    summary = (summary || "").replace(/\s+/g, " ").trim();
    const lines = (text || "").split(/\r?\n/), at = parse(text).sections.summary; if (lines.length && lines[lines.length - 1] === "") lines.pop();
    if (at === undefined) return versioned(lines.join("\n"), summary);
    let j = at + 1; while (j < lines.length && !lines[j].trim()) j++;
    if (j >= lines.length || heading(lines[j])) lines.splice(at + 1, 0, summary); else lines[j] = summary;
    return lines.join("\n");
  }
  function report(text, profileSkills) {
    const rv = review(text), c = rv.categories.map(x => x.score), secs = Object.keys(parse(text).sections), skills = rv.skills;
    const scores = {formatting: c[3] + c[4] + c[5], keywords: Math.min(20, 3 * skills.length + (secs.includes("skills") ? 5 : 0)), impact: c[0] + c[1], contact: c[2]};
    const sections = REPORT_SECTIONS.map(([key, name, max]) => { const pct = Math.round(100 * scores[key] / max); return {key, name, score: scores[key], max, percent: pct, tone: pct >= 80 ? "ok" : pct < 50 ? "warn" : ""}; });
    const percent = Math.round(100 * Object.values(scores).reduce((a, b) => a + b, 0) / REPORT_SECTIONS.reduce((a, r) => a + r[2], 0));
    const label = percent >= 80 ? "ATS-ready" : percent >= 60 ? "Almost ready" : "Needs work";
    const sugg = [], miss = missingProfileSkills(text, profileSkills);
    if (miss.length) sugg.push({section: "keywords", kind: "skills", severity: "warn", title: "Add skills you already list on your profile", detail: "These are on your profile but not on this resume: " + miss.join(", ") + ". Screeners search resumes for them.", old: "", new: miss.join(", ")});
    for (const f of rv.findings) { if (miss.length && f.message.startsWith("Add a Skills section")) continue; sugg.push({section: findingSection(f.message), kind: "tip", severity: f.severity, title: f.message, detail: "", old: "", new: ""}); }
    for (const b of rv.bullets) sugg.push({section: "impact", kind: "rewrite", severity: "warn", title: "Strengthen this bullet", detail: b.issues.slice(0, 2).join(" "), old: b.text, new: b.rewrite});
    const order = Object.fromEntries(REPORT_SECTIONS.map((r, i) => [r[0], i])), sev = {bad: 0, warn: 1, info: 2};
    sugg.sort((a, b) => order[a.section] - order[b.section] || sev[a.severity] - sev[b.severity]);
    sugg.forEach((x, i) => { x.id = "s" + i; });
    return {percent, label, sections, suggestions: sugg, stats: rv.stats, skills};
  }
  function standOut(text) {
    const p = parse(text), tips = [];
    if (!("summary" in p.sections)) tips.push({title: "Open with a short summary", detail: "Two lines on who you are and what you want. Tailor to a job writes one for a specific role."});
    const good = (p.bullets.find(b => NUM.test(b.text) && !bulletIssues(b.text).length) || {}).text || "";
    if (good) tips.push({title: "Lead with your strongest result", detail: `“${good.slice(0, 140)}” shows a result. Put it first under its role.`});
    const sk = extractSkills(text).slice(0, 5);
    if (sk.length) tips.push({title: "Name your tools", detail: "Screeners search for skills like " + sk.join(", ") + ". Keep them in a Skills section and in bullets where true."});
    if (!["leadership", "organizations", "activities"].some(k => k in p.sections)) tips.push({title: "Show campus involvement", detail: "Clubs, teams and volunteering show initiative, especially with limited work history."});
    return tips.slice(0, 4);
  }

  const NCS = {normalize, runTextRules, scorePosting, check, linkFindings, LEVELS, NEXT_STEPS, extractSkills, normalizeSkill, parseQuery, rankJobs, keywordGap,
    categoriesForMajor, qualsOf, QUAL_KINDS, review, report, standOut, addSkills, setSummary, missingProfileSkills, improveBullet, bulletIssues, tailor, versioned, relevance, assistant, toProfile, jobRequirements, fitScore, FIT_NAMES, FREE_MAIL, trustFromSignals, replyTime, median, PROFILE_FIELDS, POPULAR, CATEGORIES, WORK_TYPES, JOB_KINDS, SKILLS,
    ruleset: RULEPACK.version};
  root.NCS = NCS;
  if (typeof module !== "undefined" && module.exports) module.exports = NCS;
})(typeof window !== "undefined" ? window : globalThis);
