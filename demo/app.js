/* NoleCareerShield interactive demo. Same pages, rules and design as the real site, held in memory.
 * Every scam verdict, match, resume score and feed check comes from demo/engine.js, a line-for-line
 * port of the Python that tests/test_demo_engine.py checks against the real code. */
(function () {
"use strict";
const N = window.NCS;
const $ = s => document.querySelector(s);
const esc = s => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const cap = s => s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
const plural = (n, w, many) => `${n} ${n === 1 ? w : (many || w + "s")}`;
const PW = "Str0ng!pass";
const NOW = () => Date.now();

// ---------------- icons (same drawings as ui.py) ----------------
const ICONS = {
  home: '<path d="M4 11 12 4l8 7"/><path d="M6 10v9h12v-9"/>',
  jobs: '<rect x="3.5" y="7.5" width="17" height="12" rx="2"/><path d="M9 7.5V5.5a1.5 1.5 0 0 1 1.5-1.5h3A1.5 1.5 0 0 1 15 5.5v2"/><path d="M3.5 12.5h17"/>',
  feed: '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M8 9h8M8 12.5h8M8 16h5"/>',
  chat: '<path d="M5 5h14a1.5 1.5 0 0 1 1.5 1.5v9A1.5 1.5 0 0 1 19 17h-8l-4.5 3.5V17H5a1.5 1.5 0 0 1-1.5-1.5v-9A1.5 1.5 0 0 1 5 5z"/>',
  spark: '<path d="M12 3.5 13.8 10.2 20.5 12 13.8 13.8 12 20.5 10.2 13.8 3.5 12 10.2 10.2Z"/>',
  file: '<path d="M7 3.5h7l4 4v13H7z"/><path d="M14 3.5v4h4"/><path d="M9.5 12h6M9.5 15.5h6"/>',
  shield: '<path d="M12 3.5 19 6v6c0 4.5-3 7.5-7 8.5-4-1-7-4-7-8.5V6z"/><path d="m9 12 2.2 2.2L15.5 10"/>',
  user: '<circle cx="12" cy="8.5" r="3.5"/><path d="M5 20c1-3.6 3.8-5.5 7-5.5s6 1.9 7 5.5"/>',
  people: '<circle cx="9" cy="9" r="3"/><path d="M3.5 19c.8-3 3-4.5 5.5-4.5s4.7 1.5 5.5 4.5"/><circle cx="16.5" cy="8" r="2.5"/><path d="M15.5 13.6c2.4-.3 4.4 1.1 5 3.9"/>',
  plus: '<path d="M12 5v14M5 12h14"/>', flag: '<path d="M6 21V4"/><path d="M6 4h11l-2 4 2 4H6"/>',
  send: '<path d="M4 12 20 4l-5 16-3-7z"/>', check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
};
const icon = (n, s) => `<svg class="ic" viewBox="0 0 24 24" width="${s || 18}" height="${s || 18}" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[n] || ""}</svg>`;

// ---------------- sample data ----------------
const RESUME = `Jordan Rivera
jordan.rivera@fsu.edu | Tallahassee, FL | linkedin.com/in/jordanrivera

EDUCATION
Florida State University, B.S. Statistics, Minor in Computer Science. Expected May 2027. GPA 3.6

EXPERIENCE
Data Intern, Leon County Health Department, Summer 2025
- Responsible for cleaning survey data in Excel
- Built SQL queries to pull clinic visit counts for 12 clinics, cutting report time from 3 days to 4 hours
- Helped with making charts in Tableau for the monthly board meeting

Social Media Chair, Statistics Club, 2024-2025
- Managed the club Instagram and grew followers by 40%
- I was in charge of planning weekly study sessions

SKILLS
Python, SQL, Excel, Tableau, R, Public speaking, Spanish`;

const EXTRA_LISTINGS = [
  {id: 9, title: "Social Media Intern", company: "Garnet Analytics", category: "Marketing", work_type: "hybrid", location: "Tallahassee, FL", state: "approved",
   description: "Plan and schedule posts for our Instagram and LinkedIn, write short case-study captions, and track what performs in a weekly Excel sheet. Canva experience helps.\n\n10 to 12 hours a week during the semester. Paid internship at $16 per hour.", apply_url: "https://garnetanalytics.example/careers/social-intern"},
  {id: 10, title: "Patient Services Assistant (Part-time)", company: "Bayside Dental", category: "Healthcare", work_type: "on-site", location: "Tallahassee, FL", state: "approved",
   description: "Check patients in, schedule visits, verify insurance and keep records up to date in our practice software. Spanish is a plus. 15 hours a week, weekday afternoons. $15 per hour.", apply_url: "https://baysidedental.example/jobs"},
];
const APPLY_FIX = {1: "https://garnetanalytics.example/careers", 2: "https://baysidedental.example/jobs", 3: "https://coastalpolicylab.example/ra",
  4: "https://panhandlefreight.example/work", 5: "https://brightpathstaffing.example/apply", 6: "https://quickcashstaffing.example/apply",
  7: "https://capitalrowpartners.example/internships"};
const EMPLOYER_OF = {"Garnet Analytics": 4, "Bayside Dental": 5, "Coastal Policy Lab": 6, "QuickCash Staffing": 7, "Capital Row Partners": 8};

let S; // the whole demo state
function reset() {
  S = {users: [], students: {}, employers: {}, jobs: [], convos: [], posts: [], reports: [], inbox: [], tokens: {}, versions: [],
       session: null, admin: false, route: {name: "home", q: {}}, flash: null, draft: null, pendingDraft: null, nextId: 1, tokN: 0, itemN: 0, timers: [], candidates: [], views: {}, clicks: {}};
  const user = (email, role) => { const u = {id: S.nextId++, email, role, pw: PW, verified: true}; S.users.push(u); return u; };
  const t = NOW();
  const j = user("jordan@fsu.edu", "student"), m = user("maya@fsu.edu", "student"), d = user("dev@fsu.edu", "student");
  S.students[j.id] = {display_name: "Jordan R.", pronouns: "", major: "Statistics", minor: "Computer Science", degree: "Bachelor's", grad_term: "Spring 2027",
    headline: "Stats + CS student looking for a data internship", bio: "I like turning messy spreadsheets into answers.",
    skills: ["Python", "SQL", "Excel", "Tableau", "R", "Communication", "Spanish"], interests: ["Data & Analytics", "Research"],
    work_types: ["remote", "hybrid"], job_kinds: ["internship", "part-time"], links: {linkedin: "https://linkedin.com/in/jordanrivera"},
    resume_text: RESUME, resume_name: "Jordan_Rivera_Resume.pdf", visible: true, share_resume: false, allow_messages: true, setup_step: 3};
  S.students[m.id] = {display_name: "Maya T.", major: "Marketing", degree: "Bachelor's", grad_term: "Fall 2026", headline: "Social and content marketing",
    skills: ["Social media", "Graphic design", "Content writing", "Excel"], interests: ["Marketing"], work_types: ["hybrid"], job_kinds: ["internship"],
    links: {}, resume_text: "", visible: true, share_resume: false, allow_messages: true, setup_step: 3};
  S.students[d.id] = {display_name: "Dev P.", major: "Computer Science", degree: "Bachelor's", grad_term: "Spring 2028", headline: "",
    skills: ["Python", "JavaScript", "React", "Git"], interests: ["Software & IT"], work_types: ["remote"], job_kinds: ["internship"],
    links: {}, resume_text: "", visible: false, share_resume: false, allow_messages: true, setup_step: 3};
  // Profile sections: Jordan's come from the resume (the same import students get), plus a project, a certification and a language.
  const jp = S.students[j.id];
  Object.assign(jp, {location: "Tallahassee, FL", looking_roles: ["Data Analyst", "Research Assistant"], pref_locations: ["Tallahassee, FL", "Remote"], items: []});
  importResume(jp);
  addItem(jp, {kind: "project", title: "Campus food access dashboard", org: "STA 4102", location: "", start: "Jan 2026", end: "Apr 2026", current: false,
    description: "• Cleaned 3 semesters of survey data (2,400 responses) in R\n• Built a Tableau dashboard the Student Government food pantry uses to plan orders", url: "github.com/jordanrivera/food-access", extra: {skills: "R, Tableau, SQL"}});
  addItem(jp, {kind: "certification", title: "Google Data Analytics Certificate", org: "Coursera", location: "", start: "Dec 2025", end: "", current: false, description: "", url: "", extra: {}});
  addItem(jp, {kind: "language", title: "Spanish", org: "", location: "", start: "", end: "", current: false, description: "", url: "", extra: {proficiency: "Professional working"}});
  const mp = S.students[m.id]; mp.items = [];
  addItem(mp, {kind: "experience", title: "Social Media Intern", org: "Tally Coffee Co.", location: "Tallahassee, FL", start: "May 2025", end: "Aug 2025", current: false, description: "• Planned and posted 5 Instagram posts a week\n• Grew followers from 1,200 to 2,050", url: "", extra: {type: "Internship"}});
  addItem(mp, {kind: "education", title: "B.S. Marketing", org: "Florida State University", location: "Tallahassee, FL", start: "Aug 2022", end: "Dec 2026", current: false, description: "", url: "", extra: {major: "Marketing"}});
  const dp = S.students[d.id]; dp.items = [];
  addItem(dp, {kind: "project", title: "Seminole bus tracker", org: "Hackathon", location: "", start: "Feb 2026", end: "", current: false, description: "• React app showing live campus bus arrivals", url: "", extra: {skills: "React, JavaScript"}});
  const emp = (email, p) => { const u = user(email, "employer"); S.employers[u.id] = Object.assign({status: "approved", status_note: ""}, p); return u; };
  emp("pat@garnetanalytics.example", {company: "Garnet Analytics", website: "https://garnetanalytics.example", industry: "Technology", size: "11-50", location: "Tallahassee, FL",
    about: "We build campaign and survey dashboards for Florida nonprofits and city agencies.", contact_name: "Pat Lee", contact_title: "Campus Recruiter",
    fsu_connection: "We hire three FSU interns every summer and table at the fall career fair."});
  emp("hr@baysidedental.example", {company: "Bayside Dental", website: "https://baysidedental.example", industry: "Healthcare", size: "11-50", location: "Tallahassee, FL",
    about: "A family dental practice with two offices in Tallahassee.", contact_name: "Renee Owens", contact_title: "Office Manager",
    fsu_connection: "Part-time front desk and patient services roles for FSU pre-health students."});
  emp("lab@coastalpolicylab.example", {company: "Coastal Policy Lab", website: "https://coastalpolicylab.example", industry: "Research", size: "1-10", location: "Remote",
    about: "A small research group studying coastal resilience policy in the Southeast.", contact_name: "Dr. Ana Ruiz", contact_title: "Lab Director",
    fsu_connection: "We hire FSU undergraduates as paid research assistants each semester."});
  emp("quickcash.hiring@gmail.com", {company: "QuickCash Staffing", website: "https://quickcashstaffing.example", industry: "Other", size: "1-10", location: "",
    about: "We connect remote workers with flexible payment processing roles across the country.", contact_name: "Mike", contact_title: "HR",
    fsu_connection: "We hire students.", status: "pending"});
  emp("recruiting@capitalrowpartners.example", {company: "Capital Row Partners", website: "https://capitalrowpartners.example", industry: "Finance & Banking", size: "51-200", location: "Tallahassee, FL",
    about: "A regional wealth management firm serving North Florida families and small businesses.", contact_name: "Chris Hall", contact_title: "Talent Manager",
    fsu_connection: "Our finance internship recruits from the FSU College of Business every spring.", status: "pending"});

  const listings = NCS_SEED.concat(EXTRA_LISTINGS);
  S.jobs = listings.map((l, i) => {
    const job = Object.assign({}, l, {apply_url: APPLY_FIX[l.id] || l.apply_url, employer_id: EMPLOYER_OF[l.company] || null, age_days: (listings.length - i) * 2});
    scoreJob(job); job.review_status = l.state; job.review_label = l.state === "approved" ? "legit" : null; job.seedApproved = l.state === "approved"; return job;
  });
  S.nextJob = 11;

  // Conversations: one normal, one the scanner flagged.
  const c1 = convo(j.id, 4, 1); addMsg(c1, j.id, "Hi Pat! I saw the Marketing Data Analyst role. I've built SQL reports for the Leon County Health Department. Is it still open for the spring?", t - 7200e3);
  addMsg(c1, 4, "Hi Jordan, yes it is! Could you do a 20-minute video call Thursday afternoon? You can also apply on our careers page so HR has your resume.", t - 3000e3);
  const c2 = convo(j.id, 5, 0); addMsg(c2, 5, "Hello! We have a remote assistant opening. Text me on WhatsApp at 850-555-0142 so we can move faster, HR is swamped this week.", t - 1800e3);
  c1.messages.forEach(x => x.read = true); c2.messages.forEach(x => x.read = false);
  const jc = S.candidates.find(x => x.job === 1 && x.student === j.id); if (jc) { jc.stage = "interviewing"; jc.note = "SQL reports for the county. Video call Thursday."; }
  // Listing stats: students who opened the Garnet Analytics listing and pressed Apply (totals only).
  for (let k = 0; k < 23; k++) recordView(1, 1000 + k);
  for (let k = 0; k < 7; k++) (S.clicks[1] = S.clicks[1] || new Set()).add(1000 + k);
  // A held message only reviewers see.
  const c3 = convo(m.id, 7, 0); addMsg(c3, 7, "Congratulations, you have been pre-selected for a remote payments assistant position. You will receive a check to buy equipment from our approved vendor; deposit it and send the balance by Zelle.", t - 900e3);

  // Feed
  S.posts = [
    post(d.id, "win", "Just got my first internship offer through a listing here. Tailoring my resume to the posting made a real difference.", "", "published", t - 5400e3),
    post(4, "info_session", "Garnet Analytics is hosting an info session for FSU students interested in summer data internships. Thursday 6pm at the Career Center, room 2. Bring a resume!", "", "published", t - 9000e3),
    post(m.id, "question", "Has anyone done the Deloitte info session at the Career Center? Worth going as a sophomore?", "", "published", t - 14000e3),
    post(8, "opportunity", "Capital Row Partners is hiring two finance interns for summer 2027. FSU business majors, apply by Nov 15 on our careers page.", "https://capitalrowpartners.example/internships", "pending", t - 1200e3),
  ];
  S.posts[2].comments.push({author: j.id, body: "Yes, go. They collect resumes at the door and it's a low-pressure way to meet recruiters.", at: t - 12000e3});
  S.posts[0].helpful.add(j.id); S.posts[0].helpful.add(m.id);
}
function scoreJob(j) {
  const r = N.scorePosting(j.title, j.description, j.company, j.apply_url ? [j.apply_url] : null);
  j.score = r.score; j.band = r.band; j.findings = r.findings.slice();
  j.scam_status = {block: "held", review: "flagged"}[r.band] || "clear";
  if (r.lead_gen.flag) { if (j.scam_status === "clear") j.scam_status = "flagged";
    j.findings.push({rule_id: "lead_gen", severity: "warning", weight: 0, title: "Looks like an aggregator or lead-generation listing", why: r.lead_gen.verdict, matched: r.lead_gen.reasons.map(x => x.reason).slice(0, 4)}); }
}
function convo(student, employer, job) { const c = {id: S.convos.length + 1, student, employer, job: job || 0, messages: [], blocked_by: null, hidden: {}}; S.convos.push(c); return c; }
function addMsg(c, from, body, at) {
  const r = N.check(body);
  const m = {id: S.convos.reduce((n, x) => n + x.messages.length, 0) + 1 + Math.floor(Math.random() * 1e6), from, body, at: at || NOW(), band: r.band,
    findings: r.findings.slice(0, 5).map(f => f.title), status: r.band === "block" ? "held" : "delivered", read: false};
  c.messages.push(m); c.last = m.at; c.hidden = {};
  // A delivered message about a listing puts the student in that listing's candidate tracker.
  if (m.status === "delivered" && c.job) addCandidate(c.job, c.student, c.employer, from === c.student ? "messaged" : "invited");
  return m;
}
function post(author, kind, body, link, status, at) {
  const scan = N.check(body + (link ? "\n" + link : ""));
  return {id: S.posts.length + 1 + Math.floor(Math.random() * 1e5), author, kind, body, link: link || "", status, scan: scan.band, flags: scan.findings.slice(0, 4).map(f => f.title),
    helpful: new Set(), comments: [], reports: new Set(), at: at || NOW()};
}

// ---------------- lookups ----------------
const U = id => S.users.find(u => u.id === id);
const SP = id => S.students[id];
const EP = id => S.employers[id];
const approvedEmp = id => !!(EP(id) && EP(id).status === "approved");
const approvedJobs = () => S.jobs.filter(j => j.review_status === "approved");
const me = () => S.session;
const isStudent = () => me() && me().role === "student";
const isEmployer = () => me() && me().role === "employer";
const studentReady = p => !!(p && p.display_name && p.major);
function who(id) {
  const u = U(id); if (!u) return ["Deleted account", "", "stu"];
  if (u.role === "employer") { const p = EP(id) || {}; return [p.company || "Employer", (p.status === "approved" ? "Approved employer" : "Employer (not yet approved)") + (p.location ? " · " + p.location : ""), "emp"]; }
  const p = SP(id) || {};
  return [p.display_name || "FSU student", [p.major, p.grad_term ? "Class of " + p.grad_term.split(" ").pop() : ""].filter(Boolean).join(" · ") || "FSU student", "stu"];
}
const initials = n => esc((n || "").replace(/@/g, " ").split(/\s+/).filter(p => /^[A-Za-z0-9]/.test(p)).slice(0, 2).map(p => p[0]).join("").toUpperCase() || "?");
function person(id, link) {
  const [n, sub, kind] = who(id); const go = link === false ? "" : (kind === "emp" ? `company?id=${id}` : `u?id=${id}`);
  const nm = go ? `<a href="#" data-go="${go}" style="text-decoration:none">${esc(n)}</a>` : esc(n);
  return `<div class="person"><span class="avatar${kind === "emp" ? " emp" : ""}">${initials(n)}</span><div style="min-width:0"><div class="nm">${nm}</div><div class="sub">${esc(sub)}</div></div></div>`;
}
function ago(ts) { const d = Math.max(0, (NOW() - ts) / 1000); if (d < 60) return "just now"; if (d < 3600) return Math.floor(d / 60) + "m ago"; if (d < 86400) return Math.floor(d / 3600) + "h ago"; return Math.floor(d / 86400) + "d ago"; }
function myConvos() { const u = me(); if (!u) return []; return S.convos.filter(c => (c.student === u.id || c.employer === u.id) && !c.hidden[u.id] && c.messages.some(m => m.status === "delivered" || m.from === u.id)).sort((a, b) => b.last - a.last); }
function unread(uid) { return S.convos.filter(c => (c.student === uid || c.employer === uid) && !c.blocked_by && !c.hidden[uid]).reduce((n, c) => n + c.messages.filter(m => m.from !== uid && !m.read && m.status === "delivered").length, 0); }
const banner = (kind, text, raw) => `<div class="banner ${kind}" role="${kind === "warning" ? "alert" : "status"}">${raw ? text : esc(text)}</div>`;
const pageHead = (t, lede, num) => `<div class="page-head">${num ? `<div class="num">${esc(num)}</div>` : ""}<h1>${esc(t)}</h1>${lede ? `<p>${lede}</p>` : ""}</div>`;
const takeFlash = () => { const f = S.flash; S.flash = null; return f ? banner(f.kind, f.text, f.raw) : ""; };
const flash = (kind, text, raw) => { S.flash = {kind, text, raw}; };

// The scam score only counts scam rules; a listing flagged by the separate aggregator check says so (same as app._score_pill).
function scorePill(j) {
  const lg = j.findings.some(f => f.rule_id === "lead_gen");
  return lg && j.score < 15 ? "Aggregator · flagged" : `Scam score ${j.score} · ${j.scam_status}` + (lg ? " · aggregator" : "");
}

// ---------------- job cards ----------------
function jobCard(j, match) {
  const badge = j.scam_status === "clear" ? '<span class="badge verified">✓ Verified</span>' : '<span class="badge warning">⚠ Check carefully</span>';
  const pill = match ? (match.fit ? `<span class="pill accent" title="${esc(match.fit.label)}">Fit ${match.fit.score}</span>` : `<span class="pill accent">${match.score}% match</span>`) : "";
  const why = match && match.reasons.length ? `<div class="why">${esc(match.reasons[0])}</div>` : "";
  return `<a class="job" href="#" data-go="job?id=${j.id}"><div class="job-top"><div><div class="job-title">${esc(j.title)}</div><div class="job-co">${esc(j.company)}</div></div><div class="row" style="gap:6px">${pill}${badge}</div></div>
<div class="job-meta"><span class="chip">${esc(j.category)}</span><span class="chip">${esc(cap(j.work_type))}</span>${j.location ? `<span class="chip">${esc(j.location)}</span>` : ""}</div>${why}</a>`;
}

// ---------------- layout ----------------
const STUDENT_NAV = [["", [["home", "home", "Home"], ["jobs", "jobs", "Jobs"], ["spark", "assistant", "Job assistant"], ["feed", "feed", "Feed"], ["chat", "messages", "Messages"]]],
  ["Career tools", [["file", "resume", "Resume studio"], ["shield", "scam", "Scam check"]]], ["You", [["user", "profile", "Profile"]]]];
const EMPLOYER_NAV = [["", [["home", "home", "Home"], ["jobs", "jobs", "Jobs"], ["feed", "feed", "Feed"], ["chat", "messages", "Messages"], ["people", "talent", "Find students"]]],
  ["Hiring", [["jobs", "hiring", "Your listings"], ["plus", "post", "Post a job"], ["shield", "scam", "Scam check"]]], ["You", [["user", "profile", "Company profile"]]]];
function sidebar(active) {
  const n = unread(me().id), out = [];
  for (const [grp, items] of (isStudent() ? STUDENT_NAV : EMPLOYER_NAV)) {
    if (grp) out.push(`<div class="grp">${esc(grp)}</div>`);
    for (const [ic, go, label] of items) out.push(`<a href="#" data-go="${go}"${go === active ? ' class="on" aria-current="page"' : ""}>${icon(ic)}<span>${esc(label)}</span>${go === "messages" && n ? `<span class="count" aria-label="${n} unread">${n}</span>` : ""}</a>`);
  }
  return `<aside class="side"><nav aria-label="Main">${out.join("")}</nav><div class="tip"><b>Stay safe:</b> real employers never ask you to pay, deposit a check, or buy gift cards. <a href="#" data-go="scam">Check a message</a>.</div></aside>`;
}
function nav() {
  $("#inboxBtn").textContent = "Demo inbox" + (S.inbox.length ? ` (${S.inbox.length})` : "");
  const extra = S.admin ? '<a class="ghost" href="#" data-go="admin">Review queue</a>' : "";
  if (me()) $("#navActions").innerHTML = extra + `<span class="who">${esc(me().email)}</span><button class="ghostbtn" type="button" data-do="logout">Log out</button>` + (isEmployer() ? '<a class="btn" href="#" data-go="post">Post a job</a>' : "");
  else $("#navActions").innerHTML = extra + '<a class="ghost opt" href="#" data-go="jobs">Browse jobs</a><a class="ghost opt" href="#" data-go="scam">Scam check</a><a class="ghost" href="#" data-go="login">Log in</a><a class="btn" href="#" data-go="post">Post a job</a>';
}
const APP_PAGES = {hiring: "hiring", hjob: "hiring", home: "home", jobs: "jobs", job: "jobs", post: "post", posted: "post", assistant: "assistant", feed: "feed", messages: "messages", newmsg: "messages",
  resume: "resume", scam: "scam", profile: "profile", setup: "profile", item: "profile", talent: "talent", u: "", company: "", about: "", privacy: "", report: ""};

// ---------------- pages ----------------
const P = {};
P.home = () => {
  if (me()) return me().role === "student" ? studentHome() : employerHome();
  const n = approvedJobs().length;
  const hero = `<section class="hero"><div class="hero-in"><div>
<div class="eyebrow">For FSU students · Scam-checked</div>
<h1>Student jobs, <em>checked for scams</em> before you see them.</h1>
<p>Every listing is scanned and approved by a person. Build a profile, message verified employers, get matched by the job assistant and sharpen your resume, all in one place.</p>
<div class="cta"><a class="primary" href="#" data-go="signup?role=student">Join with your @fsu.edu email</a><a class="secondary" href="#" data-go="jobs">Browse jobs</a></div>
<div class="count">${n ? `${n} approved listing${n !== 1 ? "s" : ""} live right now` : "Approved listings will appear here"}</div></div>
<div class="hero-card" aria-label="What a checked message looks like"><span class="stamp">Scam check</span>
<b style="font-family:var(--serif);font-weight:500;font-size:19px">"You've been pre-selected for a remote assistant role. $400/week. Reply from your personal email."</b>
<div class="mini" style="border-color:var(--bad);background:var(--bad-tint);color:var(--bad)"><b>Scam. Stop here.</b><p style="color:inherit">An offer you never applied for, a flat weekly stipend, and a push off your school email.</p></div>
<div class="mini"><b>${icon("spark", 15)} Job assistant</b><p>"Remote data internships that fit my resume" returns real, reviewed listings with the reasons they match.</p></div>
<div class="row" style="margin-top:12px"><a class="b sm" href="#" data-go="scam">Try the scam check</a><a class="b sm sec" href="#" data-do="as-student">Explore as a student</a></div>
</div></div></section>
<section class="how"><div class="how-inner">
<div class="how-item"><b>Only vetted listings</b><p>Every posting is scam-scanned, then a person approves it. Employers are reviewed before they can message you.</p></div>
<div class="how-item"><b>Tools that work for you</b><p>A job assistant that knows your skills, a resume reviewer and tailorer, and a checker for any suspicious message.</p></div>
<div class="how-item"><b>An FSU-only feed</b><p>Only verified students and approved employers post, and employer posts must be opportunities or advice for FSU students.</p></div>
</div></section>`;
  const list = approvedJobs().slice().reverse().slice(0, 3);
  return {hero, body: `<h3 class="sec">Latest approved listings</h3>${list.map(j => jobCard(j)).join("")}<p style="margin:16px 0 8px"><a href="#" data-go="jobs" style="color:var(--accent-ink);font-weight:600;text-decoration:none">See all jobs →</a></p>`};
};
function studentHome() {
  const p = SP(me().id); if (!p || !p.setup_step) { go("setup?step=1"); return null; }
  const h = new Date().getHours(), hello = h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
  const recs = N.rankJobs(approvedJobs(), p, "", 3), n = unread(me().id), [pct, missing] = completion(p);
  const recHtml = recs.map(r => `<a class="job" href="#" data-go="job?id=${r.job.id}" style="margin:0 0 8px"><div class="job-top"><div><div class="job-title" style="font-size:16px">${esc(r.job.title)}</div><div class="job-co">${esc(r.job.company)}</div></div><span class="pill accent"${r.fit ? ` title="${esc(r.fit.label)}"` : ""}>${r.fit ? "Fit " + r.fit.score : r.score + "% match"}</span></div>${r.reasons.length ? `<div class="why">${esc(r.reasons[0])}</div>` : ""}</a>`).join("") || "<p>No listings yet.</p>";
  let resumeTile;
  if (p.resume_text) { const rv = N.review(p.resume_text);
    resumeTile = `<div class="tile w3"><h3>${icon("file")}Resume</h3><div class="score"><div class="ring" style="--p:${rv.score}"><b>${rv.score}</b></div><p>${esc(rv.grade)}. ${esc(rv.findings[0] ? rv.findings[0].message : "Looking good.")}</p></div><div class="foot"><a class="b sm sec" href="#" data-go="resume">Open resume studio</a></div></div>`; }
  else resumeTile = `<div class="tile w3"><h3>${icon("file")}Resume</h3><p>Add it for a score, line-by-line fixes, and a version tailored to any job.</p><div class="foot"><a class="b sm sec" href="#" data-go="resume">Add your resume</a></div></div>`;
  const posts = S.posts.filter(x => x.status === "published").sort((a, b) => b.at - a.at).slice(0, 2);
  const date = new Date().toLocaleDateString("en-US", {weekday: "long", month: "long", day: "numeric"});
  return `<div class="page-head"><div class="num">${esc(date)}</div><h1>${hello}, ${esc((p.display_name || "").split(" ")[0])}.</h1><p>Here's what's new for you. Every listing and message is scanned for scams before you see it.</p></div>
<div class="bento"><div class="tile w4 tall"><h3>${icon("spark")}Recommended for you</h3>${recHtml}<div class="foot row"><a class="b sm" href="#" data-go="assistant">Ask the job assistant</a><a class="b sm sec" href="#" data-go="jobs">All jobs</a></div></div>
<div class="tile w2 goldt"><h3>${icon("chat")}Messages</h3><div class="big">${n}</div><p>unread message${n !== 1 ? "s" : ""}</p><div class="foot"><a class="b sm sec" href="#" data-go="messages">Open messages</a></div></div>
<div class="tile w2"><h3>${icon("shield")}Scam check</h3><p>Got a DM or email about a job? Paste it and get a verdict with the evidence.</p><div class="foot"><a class="b sm sec" href="#" data-go="scam">Check a message</a></div></div>
${resumeTile}
<div class="tile w3"><h3>${icon("user")}Profile</h3><div class="meter"><i style="width:${pct}%"></i></div><p>${pct}% complete${missing.length ? ". Add " + esc(missing[0]) : ""}</p><div class="foot"><a class="b sm sec" href="#" data-go="profile">View profile</a></div></div>
<div class="tile w6"><h3>${icon("feed")}From the FSU feed</h3>${posts.map(x => `<p style="border-left:2px solid var(--line);padding-left:10px;margin-top:6px">${esc(x.body.slice(0, 120))}${x.body.length > 120 ? "…" : ""}</p>`).join("")}<div class="foot"><a class="b sm sec" href="#" data-go="feed">Open the feed</a></div></div></div>`;
}
function employerHome() {
  const p = EP(me().id); if (!p || !p.company) { go("setup?step=1"); return null; }
  const h = new Date().getHours(), hello = h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening", n = unread(me().id);
  const mine = S.jobs.filter(j => j.employer_id === me().id);
  const tile = {pending: ["goldt", "Your organization is in review", "You can post jobs now. Messaging, the student directory and feed posts open once you're approved.", '<a class="b sm sec" href="#" data-go="admin">Approve it in the reviewer view</a>'],
    approved: ["", "You're an approved employer", "You can message students, browse the directory and post opportunities to the FSU feed.", '<a class="b sm sec" href="#" data-go="talent">Find students</a>'],
    rejected: ["tint", "Your profile wasn't approved", p.status_note || "Update your details and send it again.", '<a class="b" href="#" data-go="setup?step=1">Update profile</a>']}[p.status] || ["tint", "Finish your company profile", "", '<a class="b" href="#" data-go="setup?step=1">Finish profile</a>'];
  return `<div class="page-head"><div class="num">Employer</div><h1>${hello}, ${esc(p.company)}.</h1><p>Post roles for FSU students, answer messages, and share opportunities on the feed.</p></div>
<div class="bento"><div class="tile w4 ${tile[0]}"><h3>${esc(tile[1])}</h3><p>${esc(tile[2])}</p><div class="foot">${tile[3]}</div></div>
<div class="tile w2 goldt"><h3>${icon("chat")}Messages</h3><div class="big">${n}</div><p>unread</p><div class="foot"><a class="b sm sec" href="#" data-go="messages">Open messages</a></div></div>
<div class="tile w2"><h3>${icon("jobs")}Live listings</h3><div class="big">${mine.filter(j => j.review_status === "approved").length}</div><p>${mine.filter(j => j.review_status === "pending").length} waiting for review</p><div class="foot row"><a class="b sm" href="#" data-go="hiring">Matches &amp; stats</a><a class="b sm sec" href="#" data-go="post">Post a job</a></div></div>
<div class="tile w2"><h3>${icon("people")}Find students</h3><p>Search students who opted in, by skill or major.</p><div class="foot"><a class="b sm sec" href="#" data-go="talent">Open directory</a></div></div>
<div class="tile w2"><h3>${icon("feed")}FSU feed</h3><p>Share internships, info sessions and advice. Posts must be relevant to FSU students.</p><div class="foot"><a class="b sm sec" href="#" data-go="feed">Open the feed</a></div></div></div>`;
}
function completion(p) {
  const checks = [[!!p.display_name, "your name"], [!!p.major, "your major"], [!!p.grad_term, "your graduation term"], [(p.skills || []).length >= 3, "at least 3 skills"],
    [(p.interests || []).length > 0, "the kinds of jobs you want"], [!!p.resume_text, "a resume"], [!!p.headline, "a headline"],
    [(p.items || []).some(i => i.kind === "experience"), "an experience entry"], [(p.items || []).some(i => i.kind === "education"), "your education"],
    [(p.items || []).some(i => ["project", "certification", "organization"].includes(i.kind)), "a project, certification or organization"]];
  return [Math.round(100 * checks.filter(c => c[0]).length / checks.length), checks.filter(c => !c[0]).map(c => c[1])];
}

P.jobs = () => {
  const q = S.route.q, search = (q.search || "").trim().slice(0, 200), category = N.CATEGORIES.includes(q.category) ? q.category : "", wt = N.WORK_TYPES.includes(q.work_type) ? q.work_type : "";
  const term = search.toLowerCase();
  const list = approvedJobs().slice().reverse().filter(j => (!term || [j.title, j.company, j.description].some(t => t.toLowerCase().includes(term))) && (!category || j.category === category) && (!wt || j.work_type === wt));
  const cats = [...new Set(approvedJobs().map(j => j.category))].sort();
  const chip = (name, val, cur, param) => { const qs = new URLSearchParams(); if (search) qs.set("search", search);
    if (param !== "category" && category) qs.set("category", category); if (param !== "work_type" && wt) qs.set("work_type", wt); if (val) qs.set(param, val);
    const s = qs.toString(); return `<a class="chipf${cur === val ? " active" : ""}" href="#" data-go="jobs${s ? "?" + esc(s) : ""}">${esc(name)}</a>`; };
  const p = isStudent() ? SP(me().id) : null;
  const matches = p && (p.skills || []).length ? Object.fromEntries(N.rankJobs(list, p, "", 99).map(r => [r.job.id, r])) : {};
  return (me() ? pageHead("Jobs", "Every listing here was scam-scanned and approved by a person.", "Jobs") : "") +
    `<div class="controls"><form class="searchbar" id="searchForm"><input id="search" name="search" value="${esc(search)}" placeholder="Search title, company, or keyword" aria-label="Search jobs"><button type="submit">Search</button></form>
<div class="filter-row"><span class="label">Category</span>${chip("All", "", category, "category")}${cats.map(c => chip(c, c, category, "category")).join("")}</div>
<div class="filter-row"><span class="label">Type</span>${chip("Any", "", wt, "work_type")}${N.WORK_TYPES.map(w => chip(cap(w), w, wt, "work_type")).join("")}</div></div>` +
    (list.length ? `<div class="results-head">${plural(list.length, "listing")}${search ? ` for "${esc(search)}"` : ""}</div>${list.map(j => jobCard(j, matches[j.id])).join("")}` : '<div class="empty">No listings match. Try clearing filters or a different search.</div>');
};
P.job = () => {
  const j = S.jobs.find(x => x.id === S.route.q.id);
  if (!j || j.review_status !== "approved") return '<p class="empty" style="margin:40px 0">That listing isn\'t available.</p>';
  const ban = j.scam_status === "clear" ? banner("verified", "✓ This listing passed the scam check and was approved by a reviewer. Still verify the employer through their own website before sharing personal information.")
    : banner("warning", "⚠ This listing was approved but tripped some scam signals. Read the notes below and verify the employer independently before responding.");
  const fh = j.scam_status !== "clear" ? `<div style="margin:20px 0"><b style="font-size:14px">Signals to be aware of:</b>${j.findings.filter(f => f.severity !== "note").map(f => `<div class="finding ${esc(f.severity)}"><b>${esc(f.title)}</b><br>${esc(f.why)}</div>`).join("")}</div>` : "";
  let extras = "", apply, after = "";
  if (isStudent()) {
    recordView(j.id, me().id);
    const p = SP(me().id), btns = [`<a class="b sec" href="#" data-do="to-tailor">${icon("file", 16)} Tailor my resume</a>`];
    if (j.employer_id && approvedEmp(j.employer_id)) { btns.unshift(`<a class="b ghost" href="#" data-go="newmsg?to=${j.employer_id}&amp;job=${j.id}">${icon("chat", 16)} Message the employer</a>`); btns.push(`<a class="b sec" href="#" data-go="company?id=${j.employer_id}">Company profile</a>`); }
    extras = fitPanel(j, p) + `<div class="row" style="margin:14px 0">${btns.join("")}</div>`;
    after = tailorPanel(j, p);
    apply = `<a class="apply-btn" href="${esc(j.apply_url)}" data-apply="${j.id}" target="_blank" rel="noopener noreferrer nofollow ugc">Apply →</a><p class="fine" style="text-align:left">Demo links go to example addresses.</p>`;
  } else if (isEmployer() && j.employer_id === me().id) { extras = `<div class="banner info">This is your listing. <a href="#" data-go="hjob?id=${j.id}">See ranked student matches, candidates and stats →</a></div>`; apply = ""; }
  else apply = `<div class="card" style="background:var(--info-tint);color:var(--info);border:none"><b>Log in to apply.</b> Apply links are shown to signed-in FSU students only, which keeps scrapers and scammers away from them.<div class="row" style="margin-top:12px"><a class="b sm" href="#" data-go="login?role=student&amp;next=job-${j.id}">Student log in</a><a class="b sm sec" href="#" data-go="signup?role=student&amp;next=job-${j.id}">Create student account</a></div></div>`;
  return `<a class="back" href="#" data-go="jobs">← All jobs</a>${ban}<h2 class="page" style="margin-top:8px">${esc(j.title)}</h2><p class="job-co" style="font-size:16px">${esc(j.company)}</p>
<div class="job-meta" style="margin:14px 0"><span class="chip">${esc(j.category)}</span><span class="chip">${esc(cap(j.work_type))}</span>${j.location ? `<span class="chip">${esc(j.location)}</span>` : ""}</div>${fh}${extras}<div class="detail-desc">${esc(j.description)}</div>${apply}${after}`;
};
P.post = () => {
  const v = S.draft || {}, val = n => esc(v[n] || "");
  return `${pageHead("Submit a job", "Submitting isn't publishing. Every listing is scam-scanned and then reviewed by a person before it appears.", me() ? "Hiring" : "")}${takeFlash()}
<form id="postForm" class="card" style="max-width:720px">
<div class="form-field"><label for="f-title">Job title</label><input id="f-title" name="title" required maxlength="200" placeholder="e.g. Marketing Data Analyst" value="${val("title")}"></div>
<div class="form-field"><label for="f-company">Company</label><input id="f-company" name="company" required maxlength="200" placeholder="e.g. Leaf Home" value="${val("company") || (isEmployer() ? esc(EP(me().id).company || "") : "")}"></div>
<div class="grid2"><div class="form-field"><label for="f-category">Category</label><select id="f-category" name="category">${N.CATEGORIES.map(c => `<option${v.category === c ? " selected" : ""}>${esc(c)}</option>`).join("")}</select></div>
<div class="form-field"><label for="f-work_type">Work type</label><select id="f-work_type" name="work_type">${N.WORK_TYPES.map(w => `<option value="${w}"${v.work_type === w ? " selected" : ""}>${cap(w)}</option>`).join("")}</select></div></div>
<div class="form-field"><label for="f-location">Location</label><p class="hint">City/state, or leave blank if fully remote.</p><input id="f-location" name="location" maxlength="120" placeholder="e.g. Tallahassee, FL" value="${val("location")}"></div>
<div class="form-field"><label for="f-description">Description</label><p class="hint">The full posting: responsibilities, requirements, and pay if you can share it.</p><textarea id="f-description" name="description" required maxlength="8000">${val("description")}</textarea></div>
<div class="form-field"><label for="f-apply_url">Apply URL</label><p class="hint">Where applicants should go. The scanner checks this link too.</p><input id="f-apply_url" name="apply_url" maxlength="2000" placeholder="https://..." value="${val("apply_url")}"></div>
<button class="submit-btn" type="submit">Submit for review</button><p class="fine" style="text-align:left">${isEmployer() ? "Sending as " + esc(me().email) + "." : "You'll log in or sign up before it sends."}</p></form>`;
};
P.posted = () => `${pageHead("Submitted for review")}${banner("info", "Thanks, your listing was scanned and is now waiting for a person to approve it. Nothing is published automatically. Open the reviewer view to see its score and approve it, and check the demo inbox for the receipt.")}<div class="row"><a class="b" href="#" data-go="admin">Open the reviewer view</a><a class="b sec" href="#" data-go="home">Home</a></div>`;

// ---- scam check ----
function verdictHtml(r, from) {
  const items = r.findings.slice(0, 8).map(f => `<li><b>${esc(f.title)}</b> <span class="pill ${f.severity === "critical" ? "bad" : f.severity === "warning" ? "warn" : ""}">${{critical: "strong signal", warning: "warning", note: "note"}[f.severity]}</span><span class="ev">${esc(f.why)}</span>${f.matched && f.matched.length ? `<span class="ev">Found: “${esc(f.matched.join("”, “"))}”</span>` : ""}</li>`).join("")
    + (r.lead_gen.flag ? `<li><b>Looks like a data-harvesting or aggregator ad</b><span class="ev">${esc(r.lead_gen.verdict)}</span></li>` : "")
    || '<li><b>No scam patterns matched.</b><span class="ev">The detector checked for more than 30 known student-scam patterns, the sender and every link.</span></li>';
  const plat = from ? `<p class="small" style="margin-top:8px">Sent through NoleCareerShield by <b>${esc(who(from)[0])}</b>, ${approvedEmp(from) ? "an employer our reviewers approved" : "an employer our reviewers have not approved"}.</p>` : "";
  return `<section class="verdict ${r.key}" aria-live="polite"><div class="eyebrow" style="color:inherit">Verdict</div><h2>${icon("shield", 22)}${esc(r.title)}</h2><p>${esc(r.advice)}</p>${plat}<ul class="reasons">${items}</ul></section>
<h3 class="sec">What to do next</h3><ol class="next">${N.NEXT_STEPS[r.level].map(s => `<li>${esc(s)}</li>`).join("")}</ol>`;
}
const SAMPLES = [
  ["Fake professor", "Hi! I'm Dr. Carter from the Biology department. I need a personal assistant for $400 weekly, only a few hours. Text me at 850-555-0199 from your personal email, not your fsu.edu account.", "dr.carter.fsu@gmail.com"],
  ["Check scam", "Congratulations! You've been approved for a remote data entry role. We will mail you a check to purchase your equipment from our vendor. Deposit it and send the rest via Zelle.", ""],
  ["Real recruiter", "Hi Jordan, thanks for applying to the Marketing Data Analyst role at Garnet Analytics. Are you free for a 30-minute video interview next Tuesday or Wednesday afternoon? - Pat Lee, Campus Recruiter", "pat.lee@garnetanalytics.example"],
];
P.scam = () => {
  const q = S.route.q; let top = "", text = q.text || "", sender = q.sender || "";
  if (q.m && me()) {
    const c = S.convos.find(c => c.messages.some(m => m.id === q.m)), m = c && c.messages.find(x => x.id === q.m);
    if (m && (c.student === me().id || c.employer === me().id) && m.from !== me().id && m.status === "delivered")
      top = `<div class="card"><div class="eyebrow">The message you're checking</div><p style="white-space:pre-wrap;margin-top:6px">${esc(m.body)}</p><a class="small" href="#" data-go="messages?c=${c.id}">← Back to the conversation</a></div>` + verdictHtml(N.check(m.body), m.from === c.employer ? m.from : 0);
  } else if (q.run) top = verdictHtml(N.check(text, sender));
  const form = `<form id="scamForm" class="card"><div class="form-field"><label for="c-text">The message</label><p class="hint">Paste the whole thing: text, email, LinkedIn or Handshake DM. Nothing is saved.</p>
<textarea id="c-text" name="text" required maxlength="8000" placeholder="Hi! I'm Dr. Smith from the Psychology Department. I'm looking for a personal assistant, $400 weekly...">${esc(text)}</textarea></div>
<div class="form-field"><label for="c-sender">Who sent it (optional)</label><p class="hint">The email address or name it came from. It helps spot fake FSU and company addresses.</p><input id="c-sender" name="sender" maxlength="200" value="${esc(sender)}" placeholder="e.g. careers.fsu.edu@gmail.com"></div>
<div class="row"><button class="b" type="submit">${icon("shield", 16)} Check it</button><span class="small faint">Or try a sample:</span>${SAMPLES.map((s, i) => `<button class="b sm sec" type="button" data-do="sample" data-i="${i}">${esc(s[0])}</button>`).join("")}</div></form>
<p class="aimode" style="margin-top:8px">Rule set ${esc(N.ruleset)}. The same text always gets the same verdict. On the live site, an optional AI second opinion can add caution but never lower it.</p>`;
  return pageHead("Is this message a scam?", "Paste any message about a job, internship or gig. You'll get a clear verdict, the evidence behind it, and what to do next.", "Scam check") + top + (top ? '<h3 class="sec">Check another message</h3>' : "") + form;
};

// ---- assistant ----
const SUGG = ["What jobs fit my resume?", "Remote data internships using SQL", "Part-time jobs near campus", "Review my resume", "Is this a scam: Hi! I'm Dr. Carter from the Biology dept. I need a personal assistant for $400 weekly. Text me at 850-555-0199"];
P.assistant = () => {
  if (!isStudent()) return needStudent("the job assistant");
  const p = SP(me().id), first = (p.display_name || "").split(" ")[0];
  if (!S.chat) S.chat = [{role: "bot", text: `Hi${first ? " " + first : ""}! I'm your job assistant. Ask for any kind of job, ask what fits your resume, or paste a message you got and I'll tell you if it looks like a scam.`}];
  const log = S.chat.map(t => t.role === "me" ? `<div class="say me">${esc(t.text)}</div>`
    : `<div class="say bot"><div class="who">${icon("spark", 14)} Assistant</div>${esc(t.text)}${t.jobs && t.jobs.length ? `<div class="cards">${t.jobs.map(r => jobCard(r.job, r)).join("")}</div>` : ""}${t.scam ? `<div class="row" style="margin-top:8px"><a class="b sm sec" href="#" data-go="scam">Open Scam check</a></div>` : ""}</div>`).join("");
  return pageHead("Job assistant", "Your scout for the NoleCareerShield board. It only suggests listings that passed the scam scan and a human review.", "Assistant") +
    `<div class="chat" id="chat"><div class="log" id="log" aria-live="polite">${log}</div>${S.chat.length === 1 ? `<div class="sugg">${SUGG.map((s, i) => `<button type="button" data-do="ask" data-i="${i}">${esc(s.length < 48 ? s : s.slice(0, 45) + "…")}</button>`).join("")}</div>` : ""}
<form id="askForm"><label for="q" class="hp">Your question</label><textarea id="q" name="q" required maxlength="4000" placeholder="e.g. paid research assistant jobs for a psych major" rows="1"></textarea><button class="b" type="submit" aria-label="Ask">${icon("send", 16)}</button></form></div>
<p class="aimode" style="margin-top:8px">Built-in matching · answers only from approved listings. On the live site this runs on Claude when an API key is set.</p>`;
};
function ask(q) {
  q = (q || "").trim(); if (!q) return;
  S.chat.push({role: "me", text: q});
  const out = N.assistant(q, SP(me().id), approvedJobs());
  S.chat.push({role: "bot", text: out.reply, jobs: out.jobs, scam: out.scam}); render(true);
  const l = $("#log"); if (l) l.scrollTop = l.scrollHeight;
}

// ---- resume studio ----
P.resume = () => {
  if (!isStudent()) return needStudent("the resume studio");
  const p = SP(me().id), tab = ["review", "edit", "tailor", "versions"].includes(S.route.q.tab) ? S.route.q.tab : "review";
  const head = pageHead("Resume studio", "Score it, fix it line by line, and tailor it to any job on the board. Suggestions rephrase what you wrote; they never make things up.", "Resume") + takeFlash();
  if (!p.resume_text) return head + uploadCard(true);
  const tabs = `<div class="seg" role="tablist" style="margin-bottom:18px">${[["review", "Review"], ["edit", "Edit"], ["tailor", "Tailor to a job"], ["versions", "Versions"]].map(([k, v]) => `<a href="#" data-go="resume?tab=${k}"${k === tab ? ' class="on" aria-current="page"' : ""}>${v}</a>`).join("")}</div>`;
  const note = '<p class="aimode" style="margin:10px 0 0">Using the built-in reviewer. On the live site, AI review and AI tailoring use Claude when an API key is set.</p>';
  if (tab === "review") {
    const rv = N.review(p.resume_text);
    const cats = rv.categories.map(c => `<div class="cat"><span>${esc(c.name)}</span><div class="meter${c.score >= .8 * c.max ? " ok" : c.score < .5 * c.max ? " warn" : ""}"><i style="width:${Math.round(100 * c.score / c.max)}%"></i></div><span>${c.score}/${c.max}</span></div>`).join("");
    const sev = {bad: ["bad", "Fix"], warn: ["warn", "Improve"], info: ["info", "Tip"]};
    const finds = rv.findings.map(f => `<li><span class="pill ${sev[f.severity][0]}">${sev[f.severity][1]}</span> ${esc(f.message)}</li>`).join("") || "<li>No issues found. Nice work.</li>";
    const bullets = rv.bullets.map((b, i) => `<div class="sugg-item"><div class="was">${esc(b.text)}</div><div class="now">${esc(b.rewrite)}</div><div class="iss">${esc(b.issues.join(" · "))}</div>
<div style="margin-top:8px"><button class="b sm sec" type="button" data-do="apply-rewrite" data-i="${i}">Use this rewrite</button> <span class="small faint">Fill in any [placeholder] after.</span></div></div>`).join("");
    S.lastRewrites = rv.bullets;
    return head + tabs + `<div class="split"><div class="card"><div class="score"><div class="ring" style="--p:${rv.score}"><b>${rv.score}</b></div><div><div class="eyebrow">Resume score</div><h2 style="font-family:var(--serif);font-weight:500;font-size:24px">${esc(rv.grade)}</h2><p class="small muted">${rv.stats.words} words · ${rv.stats.bullets} bullets · ${rv.stats.quantified} with numbers</p></div></div><div style="margin-top:14px">${cats}</div></div>
<div class="card"><h3 class="sec" style="margin-top:0">What to fix first</h3><ul style="list-style:none;padding:0" class="stack">${finds}</ul></div></div>
<h3 class="sec">Bullet rewrites <small>${rv.bullets.length} to improve</small></h3>${bullets || '<p class="muted">Every bullet already starts strong and has a number.</p>'}<div class="row" style="margin-top:18px"><a class="b sec" href="#" data-go="resume?tab=edit">Edit resume</a></div>${note}`;
  }
  if (tab === "edit") return head + tabs + `<div class="split"><form id="resumeSave" class="card"><div class="row between" style="margin-bottom:8px"><label for="r-text" style="margin:0">Your resume</label><span class="small faint">${esc(p.resume_name || "")}</span></div>
<textarea id="r-text" class="resume" name="text" maxlength="20000">${esc(p.resume_text)}</textarea><div class="row" style="margin-top:10px"><button class="b" type="submit">Save</button><button class="b sec" type="button" data-do="copy-resume">Copy text</button></div>
<p class="small faint" style="margin-top:8px">The live site also downloads a Word (.docx) copy.</p></form>
<div><div class="card"><h3 class="sec" style="margin-top:0">Improve a bullet</h3><p class="small muted">Paste one bullet. You'll get a stronger version that keeps your facts.</p>
<form id="bulletForm"><label for="b-text" class="hp">Bullet</label><textarea id="b-text" name="bullet" maxlength="400" required style="min-height:80px" placeholder="Responsible for posting on the club Instagram">${esc(S.bulletIn || "")}</textarea><button class="b sm" type="submit" style="margin-top:8px">${icon("spark", 14)} Improve</button></form>
${S.bulletOut ? `<div class="sugg-item"><div class="was">${esc(S.bulletOut.original)}</div><div class="now">${esc(S.bulletOut.rewrite)}</div>${S.bulletOut.tips.map(t => `<p class="small" style="margin-top:6px;color:var(--warn)">${esc(t)}</p>`).join("")}</div>` : ""}</div>
<div class="card" style="margin-top:12px">${uploadCard(false, true)}</div></div></div>${note}`;
  if (tab === "tailor") {
    const ranked = N.rankJobs(approvedJobs(), p, "", 40), sel = Number(S.route.q.job) || 0;
    let result = "";
    if (S.tailor) {
      const t = S.tailor.t, pills = (xs, cls) => xs.map(x => `<span class="pill ${cls}">${esc(x)}</span>`).join("") || '<span class="faint small">None</span>';
      result = `<div class="card" style="margin-bottom:16px"><div class="score"><div class="ring" style="--p:${t.match}"><b>${t.match}</b></div><div><div class="eyebrow">Match with</div><h2 style="font-family:var(--serif);font-weight:500;font-size:22px">${esc(S.tailor.title)}</h2><p class="small muted">Based on the skills and keywords the job asks for.</p></div></div>
<div class="split" style="margin-top:14px"><div><b class="small">Skills you show</b><div class="kw" style="margin-top:6px">${pills(t.skills_present, "ok")}</div></div><div><b class="small">Skills they want that your resume doesn't show</b><div class="kw" style="margin-top:6px">${pills(t.skills_missing, "warn")}</div></div></div>
<div style="margin-top:12px"><b class="small">Keywords to use where true</b><div class="kw" style="margin-top:6px">${pills(t.keywords_missing, "")}</div></div></div>
<h3 class="sec">Suggested summary</h3><div class="card"><p>${esc(t.summary)}</p></div>
${t.lead_bullets.length ? `<h3 class="sec">Lead with these bullets</h3><ul class="reasons">${t.lead_bullets.map(b => `<li><b>${esc(b.text)}</b><span class="ev">${esc(b.why)}</span></li>`).join("")}</ul>` : ""}
${t.gaps.length ? `<h3 class="sec">Gaps, honestly</h3><ul class="reasons">${t.gaps.map(g => `<li><b>${esc(g.skill)}</b><span class="ev">${esc(g.advice)}</span></li>`).join("")}</ul>` : ""}
<form id="versionForm" class="card" style="margin-top:16px"><div class="form-field"><label for="v-name">Save a tailored copy</label><p class="hint">Adds the summary to a copy. Your main resume doesn't change.</p><input id="v-name" name="name" maxlength="80" value="${esc(("For " + S.tailor.title).slice(0, 80))}"></div>
<details style="margin:-4px 0 14px"><summary class="small" style="cursor:pointer;color:var(--accent-ink);font-weight:600">Preview and edit the copy before saving</summary><textarea class="resume" name="body" maxlength="20000" style="margin-top:8px" aria-label="Tailored copy">${esc(N.versioned(p.resume_text, t.summary))}</textarea></details>
<button class="b" type="submit">Save version</button></form>`;
    }
    return head + tabs + result + `<form id="tailorForm" class="card" style="margin-top:16px"><div class="form-field"><label for="t-job">A job on the board</label><select id="t-job" name="job_id"><option value="">Choose a listing...</option>${ranked.map(r => `<option value="${r.job.id}"${r.job.id === sel ? " selected" : ""}>${esc(r.job.title)} · ${esc(r.job.company)} (${r.fit ? "fit " + r.fit.score : r.score + "% match"})</option>`).join("")}</select></div>
<div class="or"><span>Or paste a job description</span></div><div class="form-field"><label for="t-title">Job title</label><input id="t-title" name="title" maxlength="200" placeholder="Marketing Intern"></div>
<div class="form-field"><label for="t-desc">Job description</label><textarea id="t-desc" name="description" maxlength="8000" placeholder="Paste the posting"></textarea></div><button class="b" type="submit">Compare</button></form>${note}`;
  }
  const vs = S.versions.filter(v => v.user === me().id);
  return head + tabs + (vs.length ? `<div class="card" style="overflow-x:auto"><table class="t"><tr><th>Version</th><th>Actions</th></tr>${vs.map(v => `<tr><td><b>${esc(v.name)}</b><div class="small faint">${ago(v.at)}</div></td><td><div class="row"><button class="b sm ghost" type="button" data-do="use-version" data-id="${v.id}">Make main</button><button class="b sm danger" type="button" data-do="del-version" data-id="${v.id}">Delete</button></div></td></tr>`).join("")}</table></div>`
    : '<div class="empty">No saved versions yet. Tailor your resume to a job and save it as a version.</div>');
};
function uploadCard(first, bare) {
  return `<${bare ? "div" : 'div class="card"'}><h3 class="sec" style="margin-top:0">${first ? "Add your resume" : "Replace your resume"}</h3><form id="resumeUpload">
<div class="form-field"><label for="r-file">Upload your resume</label><p class="hint">PDF, Word (.docx) or text, up to 2 MB. It's read right here in your browser and only the text is kept.</p><input id="r-file" type="file" name="file" accept=".pdf,.docx,.txt,.md,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain"></div>
<div class="form-field"><label for="r-paste">Or paste it</label><textarea id="r-paste" name="paste" maxlength="20000" placeholder="Paste your resume text"></textarea></div>
<div class="row"><button class="submit-btn" type="submit">${first ? "Review my resume" : "Replace"}</button>${first ? '<button class="b sec" type="button" data-do="sample-resume">Use a sample resume</button>' : ""}</div></form></div>`;
}

// ---- messages ----
P.messages = () => {
  if (!me()) return needLogin("messages");
  const list = myConvos(), c = S.route.q.c ? S.convos.find(x => x.id === Number(S.route.q.c) && (x.student === me().id || x.employer === me().id)) : null;
  if (c) c.messages.forEach(m => { if (m.from !== me().id && m.status === "delivered") m.read = true; });
  const threads = list.map(x => { const other = x.student === me().id ? x.employer : x.student, vis = x.messages.filter(m => m.status === "delivered" || m.from === me().id), last = vis[vis.length - 1];
    const un = x.messages.some(m => m.from !== me().id && !m.read && m.status === "delivered"), job = x.job && S.jobs.find(j => j.id === x.job);
    return `<a href="#" data-go="messages?c=${x.id}"${c && c.id === x.id ? ' class="on"' : ""}><div class="t1"><span>${esc(who(other)[0])}</span><span class="small faint" style="font-weight:400">${ago(x.last)}${un ? '<span class="dot"></span>' : ""}</span></div><div class="t2">${job ? esc(job.title) + " · " : ""}${esc(last ? last.body : "")}</div></a>`; }).join("") || '<p class="small muted" style="padding:16px">No conversations yet.</p>';
  let right;
  if (!c) right = `<div class="convo" style="justify-content:center;align-items:center;padding:40px;text-align:center"><div><h3 class="sec" style="margin-top:0">Pick a conversation</h3><p class="small muted">${isStudent() ? "Message an approved employer from any listing or company page." : "Message students from the directory."}</p></div></div>`;
  else {
    const other = c.student === me().id ? c.employer : c.student;
    const bubbles = c.messages.filter(m => m.status === "delivered" || m.from === me().id).map(m => {
      const mine = m.from === me().id, flag = !mine && ["review", "caution"].includes(m.band);
      const pre = flag ? `<div class="scanbox${m.band === "review" ? " bad" : ""}"><b>${m.band === "review" ? "⚠ Our scanner found scam signals in this message." : "Heads up: a couple of things in this message are worth checking."}</b><ul>${m.findings.slice(0, 4).map(t => `<li>${esc(t)}</li>`).join("")}</ul><a href="#" data-go="scam?m=${m.id}">See the full check →</a></div>` : "";
      return `${pre}<div class="bubble ${mine ? "me" : "them"}${flag ? " flag" : ""}">${esc(m.body)}<span class="meta">${ago(m.at)}${!mine && !flag ? ` · <a href="#" data-go="scam?m=${m.id}" style="color:inherit">Is this a scam?</a>` : ""}</span>${m.status === "held" ? "<span class=\"meta\">Held for a safety review. A reviewer checks it before it's delivered.</span>" : ""}</div>`; }).join("");
    const closed = c.blocked_by ? `<div class="composer"><p class="small muted">${c.blocked_by === me().id ? "You blocked this conversation." : "This conversation is closed."}</p>${c.blocked_by === me().id ? '<button class="b sm sec" type="button" data-do="unblock">Unblock</button>' : ""}</div>`
      : `<form class="composer" id="sendForm"><label for="m-body" class="hp">Message</label><textarea id="m-body" name="body" maxlength="4000" required placeholder="Write a message" rows="1"></textarea><button class="b" type="submit" aria-label="Send">${icon("send", 16)}</button></form>`;
    right = `<div class="convo"><div class="convo-head">${person(other)}<div class="row">${c.blocked_by ? "" : '<button class="b sm sec" type="button" data-do="block">Block</button>'}<button class="b sm danger" type="button" data-do="report-convo">${icon("flag", 14)} Report</button><button class="b sm ghost" type="button" data-do="archive">Archive</button></div></div>
<div class="thread" id="thread">${bubbles}</div>${closed}</div>`;
  }
  return (c ? '<a class="back" href="#" data-go="messages">← All messages</a>' : pageHead("Messages", "Students and approved employers only. Every message is scanned for scam signs when it's sent.", "Messages")) + takeFlash() +
    `<div class="inbox${c ? " open" : ""}"><div class="threads">${threads}</div>${right}</div><p class="small faint" style="margin-top:10px">Links in messages aren't clickable. Never send money, gift cards or bank details to get a job. <a href="#" data-go="scam">Check a message</a></p>`;
};
P.newmsg = () => {
  if (!me()) return needLogin("messages");
  const to = Number(S.route.q.to), job = S.jobs.find(j => j.id === Number(S.route.q.job));
  const [ok, why] = canStart(me(), to);
  if (!ok) return pageHead("New message") + banner("info", why) + '<a class="b sec" href="#" data-go="messages">Messages</a>';
  return pageHead("New message", "", "Messages") + `<div class="card" style="max-width:640px">${person(to)}${job ? `<p class="small muted" style="margin-top:8px">About: ${esc(job.title)}</p>` : ""}
<form id="newMsgForm" data-to="${to}" data-job="${job ? job.id : 0}" style="margin-top:12px"><div class="form-field"><label for="n-body">Message</label><textarea id="n-body" name="body" required maxlength="4000">${isStudent() && job ? esc(`Hi! I'm interested in the ${job.title} role. `) : isEmployer() && job && S.route.q.invite ? esc(inviteText(me().id, SP(to), job)) : ""}</textarea></div><button class="submit-btn" type="submit">Send</button></form></div>`;
};
function canStart(sender, to) {
  const u = U(to); if (!u || to === sender.id) return [false, "That account isn't available."];
  if (u.role === sender.role) return [false, "Messages are between students and employers."];
  if (sender.role === "student") return approvedEmp(to) ? [true, ""] : [false, "That employer hasn't been approved yet, so it can't receive messages."];
  if (!approvedEmp(sender.id)) return [false, "Messaging opens once a reviewer approves your organization. Open the reviewer view to approve it in the demo."];
  const p = SP(to); if (!studentReady(p) || !p.allow_messages) return [false, "That student isn't accepting messages from employers."];
  if (!p.visible && !S.convos.some(c => c.student === to && c.employer === sender.id)) return [false, "That student isn't accepting messages from employers."];
  return [true, ""];
}
const REPLIES = ["Thanks for reaching out! I'll take a look and get back to you by the end of the week.", "Great to hear from you. Could you send your resume through our careers page so HR has it on file?",
  "Thanks! Are you available for a quick 15-minute call Thursday or Friday afternoon?"];
function sendMessage(c, text) {
  const m = addMsg(c, me().id, text);
  if (m.status === "held") flash("warning", "Your message was held for a safety review because it matched scam patterns. A reviewer checks it before it's delivered.");
  else {
    const other = c.student === me().id ? c.employer : c.student;
    S.inbox.unshift({to: U(other).email, subject: "You have a new message on NoleCareerShield", body: `${who(me().id)[0]} sent you a message on NoleCareerShield.\n\nRead it on the site. We never put message text in emails, so an email that includes a "message" and asks you to reply is not from us.`, link: null});
    if (isStudent() && !c.blocked_by) S.timers.push(setTimeout(() => { if (S.convos.includes(c) && !c.blocked_by) { addMsg(c, c.employer, REPLIES[c.messages.length % REPLIES.length]); if (S.route.name === "messages" || S.route.name === "home") render(true); else nav(); } }, 2600));
  }
}

// ---- feed ----
const KINDS = {question: "Question", advice: "Advice", opportunity: "Opportunity", event: "Event", win: "Win", info_session: "Info session"};
const FILTERS = {question: "Questions", advice: "Advice", opportunity: "Opportunities", event: "Events", win: "Wins", info_session: "Info sessions"};
const KIND_PILL = {question: "info", advice: "gold", opportunity: "accent", event: "gold", win: "ok", info_session: "gold"};
P.feed = () => {
  if (!me()) return pageHead("The FSU feed", "Questions, advice and opportunities from verified FSU students and employers our reviewers approved.", "Community") +
    `<div class="bento"><div class="tile w3"><h3>Students</h3><p>Sign in with your @fsu.edu account to read and post.</p><div class="foot"><a class="b" href="#" data-do="as-student">Explore as a sample student</a></div></div><div class="tile w3"><h3>Employers</h3><p>Approved employers can share internships, info sessions and advice for FSU students.</p><div class="foot"><a class="b sec" href="#" data-do="as-employer">Explore as a sample employer</a></div></div></div>`;
  const head = pageHead("The FSU feed", "Only verified FSU students and approved employers can post here. Employer posts must be opportunities or advice for FSU students.", "Community");
  if (isEmployer() && !approvedEmp(me().id)) return head + banner("info", "The feed opens to employers once a reviewer approves your organization.");
  const kind = KINDS[S.route.q.kind] ? S.route.q.kind : "all";
  const posts = S.posts.filter(p => (p.status === "published" || (p.author === me().id && ["pending", "held", "rejected"].includes(p.status))) && (kind === "all" || p.kind === kind)).sort((a, b) => b.at - a.at);
  const kinds = isStudent() ? ["question", "advice", "opportunity", "event", "win"] : ["opportunity", "advice", "event", "info_session"];
  const d = S.feedDraft || {}, rule = isStudent() ? "Share a question, advice, a win, or an opportunity with other Noles." : "Employer posts must be opportunities, events or advice for FSU students. Ads and promotions are declined. A reviewer approves each post.";
  const canPost = isStudent() ? studentReady(SP(me().id)) : true;
  const composer = canPost ? `<form id="feedForm" class="composer-card">${takeFlash()}<label for="f-body" class="hp">Post</label><textarea id="f-body" name="body" required maxlength="1500" placeholder="${esc(rule)}">${esc(d.body || "")}</textarea>
<div class="row" style="margin-top:8px"><label for="f-kind" class="hp">Type</label><select id="f-kind" name="kind" style="width:auto">${kinds.map(k => `<option value="${k}"${d.kind === k ? " selected" : ""}>${KINDS[k]}</option>`).join("")}</select>
<label for="f-link" class="hp">Link</label><input id="f-link" name="link" maxlength="300" placeholder="Link (optional)" value="${esc(d.link || "")}" style="flex:1;min-width:160px"><button class="b" type="submit">Post</button></div>${isEmployer() ? `<p class="small faint" style="margin-top:6px">${esc(rule)}</p>` : ""}</form>` : banner("info", "Set up your profile (name and major) before posting.");
  const seg = `<div class="seg" style="margin-bottom:14px"><a href="#" data-go="feed"${kind === "all" ? ' class="on"' : ""}>All</a>${Object.keys(FILTERS).map(k => `<a href="#" data-go="feed?kind=${k}"${k === kind ? ' class="on"' : ""}>${FILTERS[k]}</a>`).join("")}</div>`;
  const items = posts.map(p => {
    const st = p.status !== "published" ? `<span class="pill ${p.status === "rejected" ? "bad" : "warn"}">${{pending: "Waiting for review", held: "Held for a safety check", rejected: "Not approved"}[p.status]}</span>` : "";
    const open = S.openComments === p.id, mine = p.author === me().id, helped = p.helpful.has(me().id);
    return `<article class="post"><div class="head">${person(p.author)}<div class="row" style="gap:6px">${st}<span class="pill ${KIND_PILL[p.kind]}">${KINDS[p.kind]}</span><span class="small faint">${ago(p.at)}</span></div></div>
<div class="body">${esc(p.body)}</div>${p.link ? `<p class="lnk">${icon("jobs", 14)} <a href="${esc(p.link)}" target="_blank" rel="noopener noreferrer nofollow ugc">${esc(p.link.slice(0, 90))}</a> <span class="faint">(opens another site)</span></p>` : ""}
${p.status === "published" ? `<div class="acts"><button type="button" data-do="helpful" data-id="${p.id}"${helped ? ' class="on"' : ""}>Helpful · ${p.helpful.size}</button><button type="button" data-do="comments" data-id="${p.id}">Comments · ${p.comments.length}</button>${mine ? "" : `<button type="button" data-do="report-post" data-id="${p.id}">${p.reports.has(me().id) ? "Reported" : "Report"}</button>`}${!mine && isStudent() && U(p.author).role === "employer" && approvedEmp(p.author) ? `<a href="#" data-go="newmsg?to=${p.author}">Message</a>` : ""}${mine ? `<button type="button" data-do="del-post" data-id="${p.id}">Delete</button>` : ""}</div>` : ""}
${open ? `<div class="comments">${p.comments.map(c => `<div class="comment"><b>${esc(who(c.author)[0])}</b> ${esc(c.body)} <span class="small faint">${ago(c.at)}</span></div>`).join("") || '<p class="faint small">No comments yet.</p>'}<form class="commentForm row" data-id="${p.id}" style="margin-top:8px"><label for="cm-${p.id}" class="hp">Comment</label><input id="cm-${p.id}" name="body" maxlength="500" required placeholder="Add a comment" style="flex:1;min-width:160px"><button class="b sm" type="submit">Comment</button></form></div>` : ""}</article>`; }).join("");
  return head + composer + seg + (items || '<div class="empty">Nothing here yet. Start the conversation.</div>');
};

// ---- profiles ----
const DEGREES = ["Bachelor's", "Master's", "PhD", "Professional (JD, MD...)", "Certificate", "Other"];
const TERMS = []; for (let y = 2025; y < 2033; y++) for (const s of ["Spring", "Summer", "Fall"]) TERMS.push(`${s} ${y}`);
const INDUSTRIES = ["Technology", "Finance & Banking", "Accounting", "Consulting", "Healthcare", "Education", "Government & Public Sector", "Nonprofit", "Retail", "Hospitality & Food", "Marketing & Media", "Real Estate", "Manufacturing & Logistics", "Research", "Legal", "Sports & Recreation", "Other"];
const SIZES = ["1-10", "11-50", "51-200", "201-1,000", "1,000+"];
const opts = (vals, cur) => '<option value="">Choose...</option>' + vals.map(v => `<option${v === cur ? " selected" : ""}>${esc(v)}</option>`).join("");
const checks = (name, vals, chosen, labels) => `<div class="checks">${vals.map(v => `<label class="chk"><input type="checkbox" name="${name}" value="${esc(v)}"${(chosen || []).includes(v) ? " checked" : ""}><span>${esc((labels || {})[v] || v)}</span></label>`).join("")}</div>`;
const stepsBar = (n, names) => `<div class="stepname">Step ${n} of ${names.length} · ${esc(names[n - 1])}</div><div class="steps" aria-hidden="true">${names.map((_, i) => `<span class="${i < n ? "on" : ""}"></span>`).join("")}</div>`;
P.setup = () => {
  if (!me()) return needLogin("profile setup");
  const step = Number(S.route.q.step) || 1, err = takeFlash();
  if (isStudent()) {
    const p = SP(me().id) || (S.students[me().id] = {skills: [], interests: [], work_types: [], job_kinds: [], links: {}, allow_messages: true, setup_step: 0});
    const bar = stepsBar(step, ["About you", "Skills & goals", "Resume & privacy"]);
    if (step === 1) return `<div style="max-width:680px">${err}${bar}${pageHead("Let's set up your profile", "Employers on NoleCareerShield see this, and the job assistant uses it to find matches. It takes about two minutes.")}
<form id="setup1" class="card"><div class="grid2"><div class="form-field"><label for="p-name">Name to show</label><p class="hint">First name and last initial is fine.</p><input id="p-name" name="display_name" required maxlength="60" value="${esc(p.display_name)}" placeholder="Jordan R."></div>
<div class="form-field"><label for="p-pro">Pronouns (optional)</label><p class="hint">Shown next to your name.</p><input id="p-pro" name="pronouns" maxlength="24" value="${esc(p.pronouns)}" placeholder="she/her"></div></div>
<div class="grid2"><div class="form-field"><label for="p-major">Major</label><input id="p-major" name="major" required maxlength="80" value="${esc(p.major)}" placeholder="Statistics"></div><div class="form-field"><label for="p-minor">Minor (optional)</label><input id="p-minor" name="minor" maxlength="80" value="${esc(p.minor)}"></div></div>
<div class="grid2"><div class="form-field"><label for="p-deg">Degree</label><select id="p-deg" name="degree">${opts(DEGREES, p.degree)}</select></div><div class="form-field"><label for="p-grad">Graduating</label><select id="p-grad" name="grad_term">${opts(TERMS, p.grad_term)}</select></div></div>
<div class="form-field"><label for="p-head">Headline (optional)</label><p class="hint">One line about what you're looking for.</p><input id="p-head" name="headline" maxlength="120" value="${esc(p.headline)}" placeholder="Stats + CS student looking for a data internship"></div>
<div class="form-field"><label for="p-bio">About (optional)</label><textarea id="p-bio" name="bio" maxlength="600" style="min-height:90px">${esc(p.bio)}</textarea></div><button class="submit-btn" type="submit">Continue</button></form></div>`;
    if (step === 2) { const extra = (p.skills || []).filter(s => !N.POPULAR.includes(s));
      return `<div style="max-width:680px">${err}${bar}${pageHead("Skills and goals", "These drive your job matches. Pick what you've actually used, in class, at work or in a club.")}
<form id="setup2" class="card"><div class="form-field"><label>Skills</label><p class="hint">Pick any that fit.</p>${checks("skills", N.POPULAR, p.skills)}</div>
<div class="form-field"><label for="p-more">Other skills (optional)</label><p class="hint">Separate with commas, e.g. SPSS, Canva, Premiere Pro.</p><input id="p-more" name="more_skills" maxlength="400" value="${esc(extra.join(", "))}"></div>
<div class="form-field"><label>Kinds of jobs you want</label>${checks("interests", N.CATEGORIES.slice(0, -1), p.interests)}</div>
<div class="grid2"><div class="form-field"><label for="p-roles">Roles you're looking for (optional)</label><p class="hint">Separate with commas.</p><input id="p-roles" name="looking_roles" maxlength="300" value="${esc((p.looking_roles || []).join(", "))}" placeholder="Data Analyst, Financial Analyst"></div>
<div class="form-field"><label for="p-locs">Preferred locations (optional)</label><p class="hint">Separate with semicolons.</p><input id="p-locs" name="pref_locations" maxlength="300" value="${esc((p.pref_locations || []).join("; "))}" placeholder="Tallahassee, FL; Tampa, FL"></div></div>
<div class="grid2"><div class="form-field"><label>Work setting</label>${checks("work_types", N.WORK_TYPES, p.work_types, {remote: "Remote", hybrid: "Hybrid", "on-site": "On-site"})}</div><div class="form-field"><label>Type</label>${checks("job_kinds", N.JOB_KINDS, p.job_kinds, {internship: "Internship", "part-time": "Part-time", "full-time": "Full-time", "on-campus": "On campus"})}</div></div>
<div class="row"><a class="b sec" href="#" data-go="setup?step=1">Back</a><button class="submit-btn" type="submit">Continue</button></div></form></div>`; }
    const links = p.links || {};
    return `<div style="max-width:680px">${err}${bar}${pageHead("Resume and privacy", "Add your resume to get reviews, tailoring and better matches. You decide who can see it.")}
<form id="setup3" class="card">${p.resume_text ? `<p class="small" style="color:var(--ok)">✓ Resume on file (${esc(p.resume_name || "pasted")}). Paste a new one to replace it.</p>` : ""}
<div class="form-field"><label for="p-file">Upload your resume (optional)</label><p class="hint">PDF, Word (.docx) or text. We fill your experience, education and projects from it; you can edit everything.</p><input id="p-file" type="file" name="resume_file" accept=".pdf,.docx,.txt,.md,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain"></div>
<div class="form-field"><label for="p-paste">Or paste it</label><textarea id="p-paste" name="resume_paste" maxlength="20000" placeholder="Paste your resume here"></textarea><button class="b sm sec" type="button" data-do="fill-sample" style="margin-top:6px">Paste a sample resume</button></div>
<div class="grid2"><div class="form-field"><label for="p-li">LinkedIn (optional)</label><input id="p-li" name="linkedin" maxlength="300" value="${esc(links.linkedin || "")}" placeholder="linkedin.com/in/you"></div><div class="form-field"><label for="p-web">GitHub or portfolio (optional)</label><input id="p-web" name="website" maxlength="300" value="${esc(links.website || "")}" placeholder="github.com/you"></div></div>
<h3 class="sec" style="margin-top:6px">Privacy</h3>
<label class="toggle"><input type="checkbox" name="visible" value="1"${p.visible ? " checked" : ""}><span><b>Let approved employers find me.</b> Your name, major, class year, headline and skills appear in the student directory. Only employers our reviewers approved can see it.</span></label>
<label class="toggle"><input type="checkbox" name="share_resume" value="1"${p.share_resume ? " checked" : ""}><span><b>Share my resume with approved employers</b> who can see my profile.</span></label>
<label class="toggle"><input type="checkbox" name="allow_messages" value="1"${p.allow_messages !== false ? " checked" : ""}><span><b>Allow approved employers to message me.</b> Every message is scanned for scam signs, and you can block anyone.</span></label>
<div class="row"><a class="b sec" href="#" data-go="setup?step=2">Back</a><button class="submit-btn" type="submit">Finish</button></div></form></div>`;
  }
  const p = EP(me().id) || (S.employers[me().id] = {status: "draft"}), bar = stepsBar(step, ["Company", "Contact & FSU connection"]);
  if (step === 1) return `<div style="max-width:680px">${err}${bar}${pageHead("Tell students who you are", "A person reviews every employer before they can message students or post to the FSU feed. Clear, checkable details get approved fastest.")}
<form id="esetup1" class="card"><div class="form-field"><label for="e-co">Organization name</label><input id="e-co" name="company" required maxlength="120" value="${esc(p.company)}" placeholder="Acme Analytics"></div>
<div class="form-field"><label for="e-web">Website</label><p class="hint">Reviewers check that it matches the email you signed up with.</p><input id="e-web" name="website" required maxlength="300" value="${esc(p.website)}" placeholder="https://acme.com"></div>
<div class="grid2"><div class="form-field"><label for="e-ind">Industry</label><select id="e-ind" name="industry">${opts(INDUSTRIES, p.industry)}</select></div><div class="form-field"><label for="e-size">Size</label><select id="e-size" name="size">${opts(SIZES, p.size)}</select></div></div>
<div class="form-field"><label for="e-loc">Location</label><input id="e-loc" name="location" maxlength="120" value="${esc(p.location)}" placeholder="Tallahassee, FL"></div>
<div class="form-field"><label for="e-about">About</label><p class="hint">What you do, in plain words. At least a couple of sentences.</p><textarea id="e-about" name="about" required maxlength="1500">${esc(p.about)}</textarea></div><button class="submit-btn" type="submit">Continue</button></form></div>`;
  return `<div style="max-width:680px">${err}${bar}${pageHead("Contact and FSU connection", "Students see who they're talking to. Reviewers use your FSU connection to approve feed access.")}
<form id="esetup2" class="card"><div class="grid2"><div class="form-field"><label for="e-cn">Your name</label><input id="e-cn" name="contact_name" required maxlength="80" value="${esc(p.contact_name)}"></div><div class="form-field"><label for="e-ct">Your title</label><input id="e-ct" name="contact_title" required maxlength="80" value="${esc(p.contact_title)}" placeholder="Campus Recruiter"></div></div>
<div class="form-field"><label for="e-fsu">How do you work with FSU students?</label><p class="hint">Internships, part-time roles, career fair, alumni, Tallahassee office. Your feed posts must be opportunities or advice for FSU students.</p><textarea id="e-fsu" name="fsu_connection" required maxlength="800" style="min-height:100px">${esc(p.fsu_connection)}</textarea></div>
<div class="row"><a class="b sec" href="#" data-go="setup?step=1">Back</a><button class="submit-btn" type="submit">${["pending", "approved"].includes(p.status) ? "Save" : "Send for review"}</button></div></form></div>`;
};
function employerCard(p) {
  const pill = {approved: '<span class="pill ok">✓ Approved employer</span>', pending: '<span class="pill warn">Waiting for review</span>', rejected: '<span class="pill bad">Not approved</span>', draft: '<span class="pill">Profile not finished</span>'}[p.status] || "";
  return `<div class="card"><div class="row" style="gap:16px;align-items:flex-start"><span class="avatar lg emp">${initials(p.company)}</span><div style="flex:1;min-width:0">
<h2 style="font-family:var(--serif);font-weight:500;font-size:26px;line-height:1.2">${esc(p.company || "Your organization")}</h2><p class="muted">${[p.industry, p.size && p.size + " people", p.location].filter(Boolean).map(esc).join(" · ")}</p>
<div class="row" style="margin-top:10px">${pill}${p.website ? `<a class="b sm ghost" href="${esc(p.website)}" target="_blank" rel="noopener noreferrer nofollow">Website ↗</a>` : ""}</div></div></div>
${p.about ? `<p style="margin-top:14px;white-space:pre-wrap">${esc(p.about)}</p>` : ""}${p.fsu_connection ? `<h3 class="sec" style="font-size:16px">Working with FSU students</h3><p style="white-space:pre-wrap">${esc(p.fsu_connection)}</p>` : ""}
${p.contact_name ? `<p class="small muted" style="margin-top:12px">Contact: ${esc(p.contact_name)}, ${esc(p.contact_title)}</p>` : ""}</div>`;
}
P.profile = () => {
  if (!me()) return needLogin("your profile");
  const data = `<h3 class="sec">Your data</h3><div class="card"><div class="row between"><div><b>Download your data</b><p class="small muted">On the live site: everything stored about your account, as a JSON file.</p></div><button class="b sm sec" type="button" data-do="export">Show my data</button></div>${S.showExport ? `<pre style="margin-top:12px;white-space:pre-wrap;font:12px/1.5 var(--mono);background:var(--sunk);padding:10px;border-radius:8px;max-height:260px;overflow:auto">${esc(exportData())}</pre>` : ""}</div>
<details class="card" style="margin-top:12px"><summary style="cursor:pointer;font-weight:600;color:var(--bad)">Delete my account</summary><p class="small muted" style="margin:8px 0 12px">Deletes your profile, resume versions, feed posts and comments, and blanks the messages you sent. This can't be undone.</p>
<form id="deleteForm"><div class="form-field"><label for="d-pw">Your password</label><input id="d-pw" type="password" name="password" required maxlength="128" autocomplete="current-password"></div><button class="b danger" type="submit">Delete my account</button></form></details>`;
  if (isStudent()) {
    const p = SP(me().id); if (!p || !p.display_name) { go("setup?step=1"); return null; }
    const notice = takeFlash() + (S.profileNotice ? banner("info", S.profileNotice) : ""); S.profileNotice = "";
    return profileHtml(p, {owner: true, showLinks: true, notice, completion: completion(p)}) + `<div class="pdata">${data}</div>`;
  }
  const p = EP(me().id); if (!p || !p.company) { go("setup?step=1"); return null; }
  return takeFlash() + (p.status === "pending" ? banner("info", "A reviewer checks every organization, usually within a business day. In the demo, open the reviewer view to approve it.") : "") + pageHead("Company profile", "", "Profile") + employerCard(p) + '<div class="row" style="margin-top:12px"><a class="b sec" href="#" data-go="setup?step=1">Edit profile</a></div>' + data;
};
// ---------------- profile sections (LinkedIn x Handshake), same as profile_page.py ----------------
const ITEM_SECTIONS = [["experience", "Experience", "Add experience", "Jobs, internships, research and volunteer work."],
  ["education", "Education", "Add education", "Your degree, major, GPA and coursework."],
  ["project", "Projects", "Add project", "Class, club or personal projects. These count toward your job fit."],
  ["certification", "Certifications", "Add certification", "Licenses and certifications, finished or in progress."],
  ["organization", "Organizations", "Add organization", "Clubs, societies, teams and leadership roles."],
  ["course", "Courses", "Add course", "Courses that show what you know."], ["language", "Languages", "Add language", "Languages you speak."]];
const ITEM_KINDS = ITEM_SECTIONS.map(s => s[0]);
const ITEM_HEAD = Object.fromEntries(ITEM_SECTIONS.map(s => [s[0], s[1]]));
const EMPLOYMENT = ["Internship", "Part-time", "Full-time", "On-campus job", "Research", "Volunteer", "Freelance", "Seasonal"];
const PROFICIENCY = ["Elementary", "Limited working", "Professional working", "Full professional", "Native or bilingual"];
const KIND_LABEL = {internship: "Internships", "part-time": "Part-time", "full-time": "Full-time", "on-campus": "On-campus jobs"};
const ITEM_DATE = /^(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+|(?:spring|summer|fall|winter)\s+)?(?:19|20)\d{2}$/i;
const MAX_ITEMS = 60;
const tcase = s => String(s || "").toLowerCase().replace(/(?<![a-z])[a-z]/g, c => c.toUpperCase());

function cleanItem(f) {
  const t = (v, limit, label, req, multi) => { v = String(v || "").replace(/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/g, "").trim(); if (!multi) v = v.replace(/\s+/g, " ");
    if (v.length > limit) throw `${label} is too long (max ${limit} characters).`; if (req && !v) throw `${label} is required.`; return v; };
  const date = (v, label) => { v = t(v, 20, label); if (v && !ITEM_DATE.test(v)) throw `${label}: use a month and year like May 2025, or just a year.`; return v; };
  const link = v => { v = t(v, 300, "Link"); if (!v) return ""; if (!/^https?:\/\//i.test(v)) v = "https://" + v;
    if (!/^https?:\/\/[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?:[\/?#][^\s<>"']*)?$/.test(v)) throw "That link doesn't look like a web address."; return v; };
  const kind = f.kind; if (!ITEM_KINDS.includes(kind)) throw "Pick a section.";
  const ex = f.extra || {};
  const it = {kind, title: t(f.title, 120, "Title", kind !== "education"), org: t(f.org, 120, "Organization"), location: t(f.location, 80, "Location"),
    start: date(f.start, "Start"), end: date(f.end, "End"), current: !!f.current, description: t(f.description, 2000, "Description", false, true), url: link(f.url), extra: {}};
  if (kind === "education") {
    if (!it.org) throw "School is required.";
    const gpa = t(ex.gpa, 5, "GPA"); if (gpa && !/^[0-4](?:\.\d{1,2})?$/.test(gpa)) throw "GPA should look like 3.4 (on a 4.0 scale).";
    const cw = (Array.isArray(ex.coursework) ? ex.coursework : String(ex.coursework || "").split(/[,;]/)).map(c => t(c, 80, "Course")).filter(Boolean).slice(0, 20);
    const e = {major: t(ex.major, 80, "Major"), minor: t(ex.minor, 80, "Minor"), gpa, coursework: cw};
    for (const k in e) if (e[k] && (!Array.isArray(e[k]) || e[k].length)) it.extra[k] = e[k];
  } else if (kind === "experience") { if (EMPLOYMENT.includes(ex.type)) it.extra = {type: ex.type}; }
  else if (kind === "project") { const sk = Array.isArray(ex.skills) ? ex.skills.join(", ") : String(ex.skills || ""); if (sk.trim()) it.extra = {skills: t(sk, 200, "Skills used")}; }
  else if (kind === "language") { if (PROFICIENCY.includes(ex.proficiency)) it.extra = {proficiency: ex.proficiency}; }
  if (it.current) it.end = "";
  return it;
}
function addItem(p, it) {
  p.items = p.items || [];
  if (p.items.length >= MAX_ITEMS) throw `A profile can hold up to ${MAX_ITEMS} entries.`;
  const x = Object.assign({id: ++S.itemN}, it); p.items.push(x); return x;
}
// Add what the resume shows that the profile doesn't have yet (same rules as profile_page.import_resume).
function importResume(p) {
  const parsed = N.toProfile(p.resume_text || ""), key = i => [i.kind, i.title.toLowerCase(), i.org.toLowerCase()].join("\u0001");
  const have = new Set((p.items || []).map(key)); let added = 0;
  for (const it of parsed.items) {
    if (have.has(key(it))) continue;
    let clean; try { clean = cleanItem(it); } catch (e) { try { clean = cleanItem(Object.assign({}, it, {start: "", end: ""})); } catch (e2) { continue; } }
    try { addItem(p, clean); } catch (e) { break; }
    have.add(key(it)); added++;
  }
  p.skills = p.skills || [];
  for (const s of parsed.skills) if (!p.skills.some(x => x.toLowerCase() === s.toLowerCase()) && p.skills.length < 40) p.skills.push(s);
  return added;
}
function itemDates(it) { const a = it.start || "", b = it.current ? "Present" : (it.end || ""); return a && b ? `${a} – ${b}` : (a || b); }
const logoMark = (text, k) => `<span class="logo${k === "education" ? " edu" : ""}" aria-hidden="true">${initials(text || "?")}</span>`;
function entryHtml(it, owner) {
  const k = it.kind, ex = it.extra || {}, edit = owner && it.id ? `<a class="b sm ghost" href="#" data-go="item?id=${it.id}">Edit</a>` : "";
  let head, sub, meta, more = "", lg;
  if (k === "education") {
    head = esc(it.org); sub = [it.title, ex.major && "Major: " + ex.major, ex.minor && "Minor: " + ex.minor].filter(Boolean).map(esc).join(" · ");
    meta = [esc(itemDates(it)), ex.gpa && "GPA " + esc(ex.gpa)].filter(Boolean).join(" · ");
    if ((ex.coursework || []).length) more = `<div class="chips">${ex.coursework.map(c => `<span class="chip">${esc(c)}</span>`).join("")}</div>`;
    lg = logoMark(it.org, k);
  } else if (k === "language" || k === "course") {
    const note = k === "language" ? ex.proficiency : it.org;
    return `<div class="entry slim"><div><b>${esc(it.title)}</b>${note ? ` <span class="faint">· ${esc(note)}</span>` : ""}</div>${edit}</div>`;
  } else {
    head = esc(it.title); sub = [it.org, ex.type].filter(Boolean).map(esc).join(" · "); meta = [itemDates(it), it.location].filter(Boolean).map(esc).join(" · ");
    if (k === "project" && ex.skills) more = `<div class="chips">${ex.skills.split(",").map(s => s.trim()).filter(Boolean).map(s => `<span class="chip">${esc(s)}</span>`).join("")}</div>`;
    lg = logoMark(it.org || it.title, k);
  }
  const desc = it.description ? `<div class="desc">${esc(it.description)}</div>` : "";
  const link = it.url ? `<a class="small" href="${esc(it.url)}" target="_blank" rel="noopener noreferrer nofollow ugc">${esc(it.url.replace(/^https?:\/\//, "").slice(0, 60))} ↗</a>` : "";
  return `<div class="entry">${lg}<div class="body"><div class="row between" style="align-items:flex-start;flex-wrap:nowrap"><div style="min-width:0"><div class="t">${head}</div>${sub ? `<div class="s">${sub}</div>` : ""}${meta ? `<div class="m">${meta}</div>` : ""}</div>${edit}</div>${desc}${link}${more}</div></div>`;
}
function itemSection(kind, items, owner) {
  const [, title, add, prompt] = ITEM_SECTIONS.find(s => s[0] === kind), mine = items.filter(i => i.kind === kind);
  if (!mine.length && !owner) return "";
  const plus = owner ? `<a class="iconbtn" href="#" data-go="item?kind=${kind}" aria-label="${esc(add)}" title="${esc(add)}">${icon("plus", 18)}</a>` : "";
  const body = mine.length ? mine.map(i => entryHtml(i, owner)).join("") : `<p class="muted small">${esc(prompt)} <a href="#" data-go="item?kind=${kind}">${esc(add)}</a></p>`;
  return `<section class="card pcard" id="${kind}"><div class="phead"><h2>${esc(title)}</h2>${plus}</div><div class="entries${kind === "course" || kind === "language" ? " slimlist" : ""}">${body}</div></section>`;
}
function schoolLine(p) {
  const edu = (p.items || []).filter(i => i.kind === "education"), yr = /(?:19|20)(\d{2})/.exec(p.grad_term || "");
  return (edu.length ? edu[0].org : "Florida State University") + (yr ? ` '${yr[1]}` : "") + (p.major ? ` · ${p.major}` : "");
}
function profileHtml(p, o) {
  const owner = !!o.owner, showSections = o.showSections !== false, items = owner || showSections ? (p.items || []) : [];
  const name = p.display_name || "FSU student";
  const links = o.showLinks ? [["linkedin", "LinkedIn"], ["website", "Website"]].filter(([k]) => (p.links || {})[k]).map(([k, l]) => `<a href="${esc(p.links[k])}" target="_blank" rel="noopener noreferrer nofollow ugc">${l} ↗</a>`).join("") : "";
  const openTo = (p.job_kinds || []).map(k => KIND_LABEL[k] || k).concat((p.work_types || []).map(tcase));
  const opento = openTo.length ? `<div class="opento"><b>Open to</b> ${esc(openTo.join(" · "))}${owner ? ' <a href="#" data-go="setup?step=2">Edit</a>' : ""}</div>`
    : owner ? '<div class="opento muted"><b>Open to</b> <a href="#" data-go="setup?step=2">Add what you\'re looking for</a></div>' : "";
  const actions = owner ? `<div class="row"><a class="b sm sec" href="#" data-go="setup?step=1">Edit intro</a>${p.resume_text ? '<button class="b sm ghost" type="button" data-do="import-resume">Fill from resume</button>' : '<a class="b sm ghost" href="#" data-go="resume">Add resume</a>'}</div>` : (o.messageBtn || "");
  const hero = `<section class="card phero"><div class="pbanner" aria-hidden="true"></div><div class="pinfo"><span class="avatar xl">${initials(name)}</span>
<div class="row between" style="align-items:flex-end;gap:14px"><div style="min-width:0"><h1>${esc(name)}${p.pronouns ? ` <span class="pron">(${esc(p.pronouns)})</span>` : ""}</h1>${p.headline ? `<p class="headline">${esc(p.headline)}</p>` : ""}
<p class="school">${esc(schoolLine(p))}</p><p class="where">${esc(p.location || "Tallahassee, FL")}${links ? " · " : ""}<span class="plinks">${links}</span></p></div>${actions}</div>${opento}</div></section>`;
  const look = [["Job types", (p.job_kinds || []).map(k => KIND_LABEL[k] || k)], ["Roles", p.looking_roles || []], ["Industries", p.interests || []],
    ["Locations", p.pref_locations || []], ["Work setting", (p.work_types || []).map(tcase)]].filter(x => x[1].length)
    .map(([l, v]) => `<div class="lf"><div class="lfl">${esc(l)}</div><div class="chips">${v.slice(0, 8).map(x => `<span class="pill accent">${esc(x)}</span>`).join("")}</div></div>`).join("");
  let side = `<section class="card"><div class="phead"><h2>Looking for</h2>${owner ? `<a class="iconbtn" href="#" data-go="setup?step=2" aria-label="Edit what you're looking for">${icon("file", 16)}</a>` : ""}</div>${look || (owner ? '<p class="small muted">Tell employers and the job assistant what you want. <a href="#" data-go="setup?step=2">Add it</a></p>' : '<p class="small muted">Not shared yet.</p>')}</section>`;
  if (owner && o.completion) {
    const [pct, missing] = o.completion;
    side += `<section class="card"><div class="phead"><h2>Profile strength</h2><span class="small faint">${pct}%</span></div><div class="meter"><i style="width:${pct}%"></i></div>${missing.length ? `<p class="small muted" style="margin-top:8px">Next: add ${esc(missing.slice(0, 2).join(", "))}. A fuller profile makes your job fit scores more accurate.</p>` : '<p class="small muted" style="margin-top:8px">Complete. Your fit scores use all of it.</p>'}</section>`;
    const vis = [p.visible ? "Approved employers can find you" : "Hidden from the employer directory", p.share_resume ? "resume shared with them" : "resume private", p.allow_messages ? "messages on" : "employer messages off"].join("; ");
    side += `<section class="card"><div class="phead"><h2>Privacy</h2><a class="small" href="#" data-go="setup?step=3">Change</a></div><p class="small muted">${esc(cap(vis.toLowerCase()))}.</p></section>`;
  }
  const about = p.bio || "";
  const aboutHtml = about || owner ? `<section class="card pcard"><div class="phead"><h2>About</h2>${owner ? `<a class="iconbtn" href="#" data-go="setup?step=1" aria-label="Edit about">${icon("file", 16)}</a>` : ""}</div>${about ? `<p class="desc">${esc(about)}</p>` : '<p class="small muted">A few sentences about you and what you want next. <a href="#" data-go="setup?step=1">Write it</a></p>'}</section>` : "";
  const skills = p.skills || [];
  const skillsHtml = skills.length || owner ? `<section class="card pcard" id="skills"><div class="phead"><h2>Skills</h2>${owner ? `<a class="iconbtn" href="#" data-go="setup?step=2" aria-label="Edit skills">${icon("plus", 18)}</a>` : ""}</div>${skills.length ? `<div class="chips">${skills.map(s => `<span class="pill">${esc(s)}</span>`).join("")}</div>` : '<p class="small muted">No skills added yet.</p>'}</section>` : "";
  let main = aboutHtml + ["experience", "education", "project"].map(k => itemSection(k, items, owner)).join("") + skillsHtml + ["certification", "organization", "course", "language"].map(k => itemSection(k, items, owner)).join("");
  if (!owner && !showSections) main += '<p class="small faint">Experience, education and projects are shared with approved employers only.</p>';
  if (o.showResume && p.resume_text) main += `<section class="card pcard"><div class="phead"><h2>Resume</h2></div><div class="desc" style="font-family:var(--serif);font-size:14px">${esc(p.resume_text)}</div></section>`;
  else if (owner) main += `<section class="card pcard"><div class="phead"><h2>Resume</h2><a class="small" href="#" data-go="resume">Open resume studio</a></div>${p.resume_text ? `<p class="small muted">${esc(p.resume_name || "Resume")} on file. ${p.share_resume ? "Shared with approved employers who can see your profile." : "Only you can see it."}</p>` : '<p class="small muted">Add your resume to fill your profile in one step and get fit scores on every job.</p>'}</section>`;
  return (o.notice || "") + hero + `<div class="pgrid"><aside class="pside">${side}</aside><div class="pmain">${main}</div></div>`;
}
P.item = () => {
  if (!isStudent()) return needStudent("your profile");
  const p = SP(me().id), q = S.route.q;
  let it = q.id ? (p.items || []).find(i => i.id === q.id) : null;
  if (q.id && !it) { go("profile"); return null; }
  const kind = it ? it.kind : (ITEM_KINDS.includes(q.kind) ? q.kind : "experience");
  if (S.itemDraft) it = S.itemDraft;
  it = it || {}; const ex = it.extra || {};
  const v = k => esc(it[k] || ""), x = k => esc(Array.isArray(ex[k]) ? ex[k].join(", ") : ex[k] || "");
  const field = (fid, name, label, val, o) => { o = o || {}; return `<div class="form-field"><label for="${fid}">${label}</label>${o.hint ? `<p class="hint">${o.hint}</p>` : ""}<input id="${fid}" name="${name}" maxlength="${o.ml || 120}" value="${val}"${o.req ? " required" : ""} placeholder="${esc(o.ph || "")}"></div>`; };
  const dates = `<div class="grid2">${field("i-start", "start", "Start", v("start"), {ph: "Aug 2025", ml: 20})}${field("i-end", "end", "End", v("end"), {ph: "May 2026", ml: 20})}</div><label class="toggle"><input type="checkbox" name="current" value="1"${it.current ? " checked" : ""}><span>I'm currently doing this</span></label>`;
  const desc = hint => `<div class="form-field"><label for="i-desc">Description</label><p class="hint">${hint || "What you did and what came of it. One point per line works well."}</p><textarea id="i-desc" name="description" maxlength="2000">${v("description")}</textarea></div>`;
  const select = (id, name, label, vals, cur) => `<div class="form-field"><label for="${id}">${label}</label><select id="${id}" name="${name}"><option value="">Choose...</option>${vals.map(t => `<option${cur === t ? " selected" : ""}>${t}</option>`).join("")}</select></div>`;
  const body = {
    experience: () => field("i-title", "title", "Title", v("title"), {req: 1, ph: "Data Analyst Intern"}) + field("i-org", "org", "Company or organization", v("org"), {ph: "Leon County Health Department"})
      + `<div class="grid2">${select("i-type", "x_type", "Type", EMPLOYMENT, ex.type)}${field("i-loc", "location", "Location", v("location"), {ph: "Tallahassee, FL or Remote", ml: 80})}</div>` + dates + desc(),
    education: () => field("i-org", "org", "School", v("org"), {req: 1, ph: "Florida State University"}) + field("i-title", "title", "Degree", v("title"), {ph: "Bachelor of Science"})
      + `<div class="grid2">${field("i-major", "x_major", "Major", x("major"), {ml: 80, ph: "Statistics"})}${field("i-minor", "x_minor", "Minor", x("minor"), {ml: 80})}</div>`
      + `<div class="grid2">${field("i-start", "start", "Start", v("start"), {ph: "Aug 2025", ml: 20})}${field("i-end", "end", "Graduation (or expected)", v("end"), {ph: "May 2027", ml: 20})}</div>`
      + field("i-gpa", "x_gpa", "GPA (optional)", x("gpa"), {hint: "Only add it if you're comfortable sharing it. Jobs that ask for a minimum GPA use it.", ml: 5, ph: "3.4"})
      + field("i-cw", "x_coursework", "Relevant coursework", x("coursework"), {hint: "Separate with commas.", ml: 600, ph: "Business Analytics, Statistics I"}) + desc("Honors, activities or a thesis."),
    project: () => field("i-title", "title", "Project name", v("title"), {req: 1, ph: "Personal budget dashboard"}) + field("i-org", "org", "Associated with (optional)", v("org"), {hint: "A class, club, hackathon or company.", ph: "ISM 3011"})
      + field("i-url", "url", "Link (optional)", v("url"), {hint: "GitHub, a live site or a file.", ml: 300, ph: "github.com/you/project"})
      + field("i-skills", "x_skills", "Skills used", x("skills"), {hint: "Separate with commas. These count toward your fit score.", ml: 200, ph: "Python, SQL, Excel"}) + dates + desc(),
    certification: () => field("i-title", "title", "Name", v("title"), {req: 1, ph: "Microsoft Office Specialist: Excel Expert"}) + field("i-org", "org", "Issuing organization", v("org"), {ph: "Microsoft"})
      + `<div class="grid2">${field("i-start", "start", "Issued", v("start"), {ph: "Mar 2026", ml: 20})}${field("i-end", "end", "Expires (optional)", v("end"), {ml: 20})}</div>` + field("i-url", "url", "Credential link (optional)", v("url"), {ml: 300}),
    organization: () => field("i-org", "org", "Organization", v("org"), {req: 1, ph: "The Finance Society"}) + field("i-title", "title", "Role", v("title"), {req: 1, ph: "Member"}) + dates + desc(),
    course: () => field("i-title", "title", "Course name", v("title"), {req: 1, ph: "Business Analytics"}) + field("i-org", "org", "Course code (optional)", v("org"), {ph: "QMB 3200"}),
    language: () => field("i-title", "title", "Language", v("title"), {req: 1, ph: "Spanish", ml: 60}) + select("i-prof", "x_proficiency", "Proficiency", PROFICIENCY, ex.proficiency),
  }[kind]();
  const editing = !!(q.id), heading = (editing ? "Edit " : "Add ") + (kind === "education" ? "education" : ITEM_HEAD[kind].toLowerCase().replace(/s$/, ""));
  return `<a class="back" href="#" data-go="profile#${kind}">← Profile</a>${pageHead(heading)}${takeFlash()}<form id="itemForm" data-kind="${kind}" data-id="${q.id || 0}" class="card" style="max-width:680px">${body}
<div class="row"><button class="submit-btn" type="submit">Save</button><a class="b sec" href="#" data-go="profile#${kind}">Cancel</a></div></form>${editing ? `<button class="b danger sm" type="button" data-do="del-item" data-id="${q.id}" style="margin-top:12px">Delete this entry</button>` : ""}`;
};

// ---------------- job fit + tailoring on every listing, same as jobfit.py ----------------
const MARK = {met: "✓", missing: "!", unknown: "?"};
function fitPanel(job, p) {
  if (!p || !((p.skills || []).length || p.resume_text || (p.items || []).length))
    return '<section class="card" style="margin:16px 0"><h3 class="sec" style="margin-top:0">How well you fit</h3><p class="muted small">Add your skills, experience or resume and every listing shows a fit score built from your whole profile.</p><div class="row" style="margin-top:10px"><a class="b sm" href="#" data-go="profile">Build my profile</a><a class="b sm sec" href="#" data-go="resume">Add my resume</a></div></section>';
  const f = N.fitScore(job, p), tone = f.score >= 65 ? "ok" : f.score < 45 ? "warn" : "";
  const parts = f.parts.map(x => `<div class="cat"><span>${esc(x.name)}</span><div class="meter${x.score >= 75 ? " ok" : x.score < 40 ? " warn" : ""}"><i style="width:${x.score}%"></i></div><span>${x.score}</span><div class="why2">${esc(x.detail)}</div></div>`).join("");
  const found = f.matched.slice(0, 8).map(m => `<li class="met"><span class="st">✓</span><div><b>${esc(m.skill)}</b><span class="ev">Found in ${esc(m.where.slice(0, 2).map(w => w.replace(/^Your /, "your ")).join(", "))}</span></div></li>`).join("");
  const checks = f.checklist.map(c => `<li class="${c.status}"><span class="st">${MARK[c.status]}</span><div>${esc(c.text)}${c.evidence ? `<span class="ev">${esc(c.evidence)}</span>` : ""}</div></li>`).join("");
  const rel = f.relevant.slice(0, 4).map(r => `<li class="met"><span class="st">✓</span><div><b>${esc(r.where)}</b><span class="ev">Mentions ${esc(r.hits.slice(0, 3).join(", "))}</span></div></li>`).join("");
  const conf = {low: "Your profile is thin, so this is a rough estimate. Add experience, projects and a resume to sharpen it.", medium: "Based on part of your profile. Adding more sections makes it more accurate.",
    high: "Based on your whole profile: skills, resume, experience, projects, education and what you're looking for."}[f.confidence];
  return `<section class="card" style="margin:16px 0" id="fit"><div class="fit"><div class="ring" style="--p:${f.score}"><b>${f.score}</b></div><div><div class="eyebrow">Your fit for this job</div><div class="fitlabel">${esc(f.label)} <span class="pill ${tone}">${f.score}/100</span></div><p class="small muted" style="margin-top:4px">${esc(conf)}</p></div></div>
<div class="fitparts">${parts}</div><div class="split" style="margin-top:14px"><div><h4 class="small" style="margin-bottom:8px">What they ask for</h4><ul class="checklist">${checks || '<li class="unknown"><span class="st">?</span><div>The posting doesn\'t list specific requirements.</div></li>'}</ul></div>
<div><h4 class="small" style="margin-bottom:8px">Where your profile backs it up</h4><ul class="checklist">${rel}${found || '<li class="unknown"><span class="st">?</span><div>Nothing in your profile matches the skills they list yet.</div></li>'}</ul></div></div></section>`;
}
function tailorPanel(job, p) {
  if (!p || !p.resume_text)
    return '<section class="card" style="margin:16px 0" id="tailor"><h3 class="sec" style="margin-top:0">Tailor your resume to this job</h3><p class="muted small">Add your resume and you\'ll get a summary written for this role, the bullets to lead with, and the keywords to use where they\'re true.</p><a class="b sm" href="#" data-go="resume" style="margin-top:10px">Add my resume</a></section>';
  const t = N.tailor(p.resume_text, job.title, job.description, p), pills = (xs, cls) => xs.map(x => `<span class="pill ${cls}">${esc(x)}</span>`).join("") || '<span class="faint small">None</span>';
  const lead = t.lead_bullets.map(b => `<li><b>${esc(b.text)}</b><span class="ev">${esc(b.why)}</span></li>`).join("");
  return `<section class="card" style="margin:16px 0" id="tailor"><div class="row between"><h3 class="sec" style="margin:0">Tailor your resume to this job</h3><a class="b sm sec" href="#" data-go="resume?tab=tailor&amp;job=${job.id}">Open in resume studio</a></div>
<div class="split" style="margin-top:12px"><div><b class="small">Skills your resume shows</b><div class="kw" style="margin-top:6px">${pills(t.skills_present, "ok")}</div></div><div><b class="small">Skills they want that your resume doesn't show</b><div class="kw" style="margin-top:6px">${pills(t.skills_missing, "warn")}</div></div></div>
<div style="margin-top:12px"><b class="small">Words from the posting to use where true</b><div class="kw" style="margin-top:6px">${pills(t.keywords_missing, "")}</div></div>
<h4 class="small" style="margin:16px 0 6px">Suggested summary for this job</h4><div class="sugg-item" style="margin-top:0"><div class="now" style="margin-top:0">${esc(t.summary)}</div><button class="b sm sec" type="button" data-do="copy" data-text="${esc(t.summary)}" style="margin-top:8px">Copy</button></div>
${lead ? `<h4 class="small" style="margin:16px 0 6px">Lead with these bullets</h4><ul class="reasons" style="margin-top:0">${lead}</ul>` : ""}
<form id="jobVersionForm" data-name="${esc(("For " + job.title + " at " + job.company).slice(0, 80))}" style="margin-top:16px"><details><summary class="small" style="cursor:pointer;color:var(--accent-ink);font-weight:600">Preview and edit the tailored copy</summary>
<textarea class="resume" name="body" maxlength="20000" style="margin-top:8px" aria-label="Tailored copy">${esc(N.versioned(p.resume_text, t.summary))}</textarea></details>
<button class="b sm" type="submit" style="margin-top:10px">Save a tailored copy</button> <span class="small faint">Your main resume doesn't change.</span></form></section>`;
}

// ---------------- reading PDF and Word resumes in the browser ----------------
const PDFJS = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/";
let pdfReady = null;
const loadScript = src => new Promise((ok, bad) => { const s = document.createElement("script"); s.src = src; s.crossOrigin = "anonymous"; s.onload = ok; s.onerror = () => bad(new Error("load")); document.head.appendChild(s); });
function loadPdfJs() {
  // pdf.worker loaded as a plain script lets pdf.js parse on the page itself, so no worker file has to be allowed.
  if (!pdfReady) { pdfReady = loadScript(PDFJS + "pdf.min.js").then(() => loadScript(PDFJS + "pdf.worker.min.js")).then(() => { window.pdfjsLib.GlobalWorkerOptions.workerSrc = PDFJS + "pdf.worker.min.js"; });
    pdfReady.catch(() => { pdfReady = null; }); }
  return pdfReady;
}
async function pdfText(buf) {
  try { await loadPdfJs(); } catch (e) { throw "The PDF reader didn't load (are you offline?). Paste the text instead."; }
  let doc;
  try { doc = await window.pdfjsLib.getDocument({data: new Uint8Array(buf), isEvalSupported: false, disableFontFace: true}).promise; }
  catch (e) { throw e && e.name === "PasswordException" ? "That PDF is password-protected. Export it again without a password, or paste the text." : "Couldn't read that PDF. Try exporting it again, or paste the text."; }
  if (doc.numPages > 6) throw "That PDF is longer than 6 pages. A student resume should be one page.";
  const lines = [];
  for (let i = 1; i <= doc.numPages; i++) {
    const tc = await (await doc.getPage(i)).getTextContent(); let line = "", lastY = null;
    for (const it of tc.items) {
      if (typeof it.str !== "string") continue;
      const y = it.transform[5];
      if (lastY !== null && Math.abs(y - lastY) > 2 && line.trim()) { lines.push(line); line = ""; }
      line += it.str; lastY = y;
      if (it.hasEOL) { lines.push(line); line = ""; lastY = null; }
    }
    if (line.trim()) lines.push(line);
  }
  return lines.join("\n");
}
const XML_ENT = {amp: "&", lt: "<", gt: ">", quot: '"', apos: "'"};
const unxml = s => s.replace(/&(#x[0-9a-f]+|#\d+|amp|lt|gt|quot|apos);/gi, (m, e) => e[0] === "#" ? String.fromCodePoint(parseInt(e[1] === "x" || e[1] === "X" ? e.slice(2) : e.slice(1), e[1] === "x" || e[1] === "X" ? 16 : 10)) : XML_ENT[e.toLowerCase()]);
async function docxText(buf) {
  // A .docx is a zip: find word/document.xml in the central directory, inflate it, keep the text (same as resume_engine._docx_text).
  const bad = "That file isn't a Word document (.docx).", u8 = new Uint8Array(buf), dv = new DataView(buf);
  let eocd = -1;
  for (let i = u8.length - 22; i >= Math.max(0, u8.length - 65557); i--) if (dv.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
  if (eocd < 0) throw bad;
  const n = dv.getUint16(eocd + 10, true); let p = dv.getUint32(eocd + 16, true), entry = null;
  if (n > 400) throw "That document is too large to read.";
  const dec = new TextDecoder();
  for (let k = 0; k < n; k++) {
    if (p + 46 > u8.length || dv.getUint32(p, true) !== 0x02014b50) throw bad;
    const nl = dv.getUint16(p + 28, true), name = dec.decode(u8.subarray(p + 46, p + 46 + nl));
    if (name === "word/document.xml") entry = {method: dv.getUint16(p + 10, true), csize: dv.getUint32(p + 20, true), usize: dv.getUint32(p + 24, true), off: dv.getUint32(p + 42, true)};
    p += 46 + nl + dv.getUint16(p + 30, true) + dv.getUint16(p + 32, true);
  }
  if (!entry || dv.getUint32(entry.off, true) !== 0x04034b50) throw bad;
  if (entry.usize > 6 * 1024 * 1024) throw "That document is too large to read.";
  const start = entry.off + 30 + dv.getUint16(entry.off + 26, true) + dv.getUint16(entry.off + 28, true), data = u8.subarray(start, start + entry.csize);
  let xmlBytes;
  if (entry.method === 0) xmlBytes = data;
  else if (entry.method === 8 && typeof DecompressionStream !== "undefined") xmlBytes = new Uint8Array(await new Response(new Blob([data]).stream().pipeThrough(new DecompressionStream("deflate-raw"))).arrayBuffer());
  else throw "This browser can't open that Word file. Paste the text instead.";
  const xml = dec.decode(xmlBytes), paras = [];
  for (const m of xml.matchAll(/<w:p[ >][\s\S]*?<\/w:p>|<w:p\/>/g)) {
    const para = m[0].replace(/<w:tab\/>/g, "\t").replace(/<w:br[^>]*\/>/g, "\n");
    paras.push((para.includes("<w:numPr>") ? "• " : "") + unxml([...para.matchAll(/<w:t(?:\s[^>]*)?>([\s\S]*?)<\/w:t>/g)].map(r => r[1]).join("")));
  }
  return paras.join("\n");
}
function cleanResumeText(t) {
  t = t.replace(/\r\n?/g, "\n").replace(/\t/g, "  ").replace(/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/g, "");
  t = t.replace(/[  ]+\n/g, "\n").replace(/^[  ]*[•▪●◦‣■□➢►–]\s*/gm, "• ").replace(/\n{3,}/g, "\n\n");
  return t.trim().slice(0, 20000);
}
// Resolves to the resume text, or rejects with a message for the student.
async function readResumeFile(file) {
  if (file.size > 2 * 1024 * 1024) throw "That file is larger than 2 MB.";
  const name = file.name.toLowerCase(), buf = await file.arrayBuffer(), head = new Uint8Array(buf.slice(0, 4));
  let text;
  if (name.endsWith(".pdf") || String.fromCharCode(...head) === "%PDF") text = await pdfText(buf);
  else if (name.endsWith(".docx") || (head[0] === 0x50 && head[1] === 0x4b)) text = await docxText(buf);
  else if (/\.(txt|md)$/.test(name)) text = new TextDecoder().decode(buf);
  else throw "Upload a PDF, a Word document (.docx), or a text file.";
  text = cleanResumeText(text);
  if (text.length < 80) throw name.endsWith(".pdf") ? "That PDF has almost no text we can read (it may be a scanned image). Paste the text instead." : "That's too short to be a resume. Paste the whole thing.";
  return text;
}

// ---------------- employer hiring tools, same as hiring.py ----------------
const STAGES = [["new", "New"], ["reviewing", "Reviewing"], ["interviewing", "Interviewing"], ["offer", "Offer"], ["hired", "Hired"], ["declined", "Not moving forward"]];
const STAGE_NAME = Object.fromEntries(STAGES);
const SOURCES = {messaged: ["Messaged you", "accent"], invited: ["You invited", "gold"], saved: ["Saved from matches", ""]};
const JOB_STATUS = {approved: ["ok", "Live"], pending: ["warn", "In review"], rejected: ["bad", "Not approved"], removed: ["bad", "Removed"]};
function addCandidate(job, student, employer, source) {
  if (!job || S.candidates.some(c => c.job === job && c.student === student)) return false;
  S.candidates.push({job, student, employer, stage: "new", source, note: "", at: NOW(), updated: NOW()}); return true;
}
const recordView = (jid, uid) => { (S.views[jid] = S.views[jid] || new Set()).add(uid); };
function jobStats(j) {
  const cands = S.candidates.filter(c => c.job === j.id), stages = {};
  cands.forEach(c => { stages[c.stage] = (stages[c.stage] || 0) + 1; });
  return {views: (S.views[j.id] || new Set()).size, clicks: (S.clicks[j.id] || new Set()).size, candidates: cands.length, stages,
    messaged: S.convos.filter(c => c.job === j.id && c.employer === j.employer_id && c.messages.length && c.messages[0].from === c.student).length};
}
function rankedMatches(j) {
  return Object.keys(S.students).map(Number).filter(id => { const p = SP(id); return U(id) && p.visible && studentReady(p) && ((p.skills || []).length || p.resume_text || (p.items || []).length); })
    .map(id => [N.fitScore(j, SP(id)), SP(id), id]).sort((a, b) => b[0].score - a[0].score || a[1].display_name.localeCompare(b[1].display_name)).slice(0, 40);
}
const statTile = (n, l, s) => `<div class="stat"><div class="n">${n}</div><div class="l">${esc(l)}</div>${s ? `<div class="s">${esc(s)}</div>` : ""}</div>`;
function evidence(f) {
  const bits = f.matched.slice(0, 3).map(m => `<b>${esc(m.skill)}</b> <span class="faint">(${esc(m.where[0].replace("Your skills list", "skills list").replace("Your resume", "resume").replace("Your headline and about", "about"))})</span>`);
  const met = f.checklist.filter(c => c.status === "met").length;
  if (f.checklist.length) bits.push(`<span class="faint">${met} of ${f.checklist.length} requirements met</span>`);
  return bits.join(" · ");
}
function inviteText(eid, p, j) {
  const e = EP(eid) || {}, first = (p.display_name || "").split(" ")[0];
  return `Hi ${first}! ${e.contact_name && e.company ? `I'm ${e.contact_name}, ${e.contact_title} at ${e.company}. ` : ""}Your profile looks like a strong fit for our ${j.title} role, and we'd love for you to apply. You'll find the listing and the Apply link on NoleCareerShield. Happy to answer any questions here.`;
}
P.hiring = () => {
  if (!isEmployer()) return needLogin("your listings", "employer");
  const head = pageHead("Your listings", "Views, Apply clicks, ranked student matches and a candidate tracker for every listing you post.", "Hiring");
  const mine = S.jobs.filter(j => j.employer_id === me().id).slice().reverse();
  if (!mine.length) return head + '<div class="empty">No listings yet. <a href="#" data-go="post">Post your first job</a> and it shows up here once it\'s submitted.</div>';
  return head + `<div class="row" style="margin-bottom:14px"><a class="b" href="#" data-go="post">${icon("plus", 16)} Post a job</a></div>` + mine.map(j => {
    const s = jobStats(j), [tone, label] = JOB_STATUS[j.review_status] || ["", j.review_status];
    return `<a class="card lift hjob" href="#" data-go="hjob?id=${j.id}"><div class="row between" style="align-items:flex-start"><div style="min-width:0"><div class="job-title">${esc(j.title)}</div><div class="job-co">${esc(j.company)} · ${esc(cap(j.work_type))}${j.location ? " · " + esc(j.location) : ""}</div></div><span class="pill ${tone}">${esc(label)}</span></div>
<div class="stats sm">${statTile(s.views, "students viewed")}${statTile(s.clicks, "clicked Apply")}${statTile(s.messaged, "messaged you")}${statTile(s.candidates, "candidates")}</div></a>`; }).join("");
};
P.hjob = () => {
  if (!isEmployer()) return needLogin("your listings", "employer");
  const j = S.jobs.find(x => x.id === S.route.q.id && x.employer_id === me().id);
  if (!j) return pageHead("Listing not found") + '<a class="b sec" href="#" data-go="hiring">Your listings</a>';
  const tab = S.route.q.tab === "candidates" ? "candidates" : "matches", s = jobStats(j), [tone, label] = JOB_STATUS[j.review_status] || ["", j.review_status];
  const cands = S.candidates.filter(c => c.job === j.id).sort((a, b) => b.updated - a.updated), live = j.review_status === "approved";
  const stageBits = STAGES.filter(([k]) => s.stages[k]).map(([k, v]) => `${s.stages[k]} ${v.toLowerCase()}`).join(" · ");
  let content;
  if (!approvedEmp(me().id)) content = banner("info", "Ranked matches and student profiles open once a reviewer approves your organization. Your listing's stats are already counting.");
  else if (tab === "matches") {
    const ms = rankedMatches(j), saved = new Set(cands.map(c => c.student)), strong = ms.filter(m => m[0].score >= 65).length;
    content = (live ? "" : banner("info", "Invites open once this listing is approved. You can already see who fits and save them.")) + (ms.length
      ? `<p class="small muted" style="margin-bottom:12px"><b>${strong}</b> good or strong fit${strong !== 1 ? "s" : ""} among ${ms.length} students ranked. Each score uses the student's whole profile: skills, experience, projects, education, certifications and what they're looking for.</p>` +
        ms.map(([f, p, id]) => `<div class="card mcard"><div class="row between" style="align-items:flex-start;gap:12px"><div class="row" style="gap:12px;align-items:center;min-width:0"><div class="ring sm" style="--p:${f.score}"><b>${f.score}</b></div>${person(id)}</div><span class="pill ${f.score >= 65 ? "ok" : f.score < 45 ? "warn" : ""}">${esc(f.label)}</span></div>
${p.headline ? `<p style="margin-top:8px">${esc(p.headline)}</p>` : ""}<p class="small" style="margin-top:8px">${evidence(f)}</p><div class="chips" style="margin-top:8px">${f.parts.map(x => `<span class="chip" title="${esc(x.detail)}">${esc(x.name)} ${x.score}</span>`).join("")}</div>
<div class="row" style="margin-top:12px">${live && p.allow_messages ? `<a class="b sm" href="#" data-go="newmsg?to=${id}&amp;job=${j.id}&amp;invite=1">${icon("chat", 14)} Invite to apply</a>` : ""}${saved.has(id) ? '<span class="pill ok">In candidates</span>' : `<button class="b sm sec" type="button" data-do="save-cand" data-id="${id}">Save to candidates</button>`}<a class="b sm ghost" href="#" data-go="u?id=${id}">View profile</a></div></div>`).join("")
      : '<div class="empty">No students match yet. Matches come from students who made their profile visible to approved employers.</div>');
  } else content = cands.length ? `<p class="small muted" style="margin-bottom:12px">${esc(stageBits)}. Stages and notes are private to your organization.</p>` + cands.map(c => {
      const p = SP(c.student); if (!p) return "";
      const f = N.fitScore(j, p), [src, st] = SOURCES[c.source] || [c.source, ""], convo = S.convos.find(x => x.student === c.student && x.employer === me().id);
      const msg = convo ? `<a class="b sm ghost" href="#" data-go="messages?c=${convo.id}">Open conversation</a>` : live && p.allow_messages ? `<a class="b sm ghost" href="#" data-go="newmsg?to=${c.student}&amp;job=${j.id}&amp;invite=1">Invite to apply</a>` : "";
      return `<div class="card mcard" id="c${c.student}"><div class="row between" style="align-items:flex-start;gap:12px"><div class="row" style="gap:12px;align-items:center;min-width:0"><div class="ring sm" style="--p:${f.score}"><b>${f.score}</b></div>${person(c.student)}</div><div class="row"><span class="pill ${st}">${esc(src)}</span><span class="small faint">${ago(c.at)}</span></div></div>
<p class="small" style="margin-top:8px">${evidence(f)}</p><form class="cform stageForm" data-student="${c.student}"><div class="form-field"><label for="st${c.student}">Stage</label><select id="st${c.student}" name="stage">${STAGES.map(([k, v]) => `<option value="${k}"${k === c.stage ? " selected" : ""}>${esc(v)}</option>`).join("")}</select></div>
<div class="form-field"><label for="nt${c.student}">Private note</label><input id="nt${c.student}" name="note" maxlength="300" value="${esc(c.note)}" placeholder="Only your team sees this"></div><button class="b sm" type="submit">Update</button></form>
<div class="row" style="margin-top:8px">${msg}<a class="b sm ghost" href="#" data-go="u?id=${c.student}">View profile</a></div></div>`; }).join("")
    : '<div class="empty">No candidates yet. Students appear here when they message you about this listing, when you invite them, or when you save them from the ranked matches.</div>';
  return `<a class="back" href="#" data-go="hiring">← Your listings</a>${takeFlash()}<div class="row between" style="align-items:flex-start;margin-top:6px"><div><h2 class="page" style="margin:0">${esc(j.title)}</h2><p class="job-co">${esc(j.company)} · ${esc(cap(j.work_type))}${j.location ? " · " + esc(j.location) : ""}</p></div><div class="row"><span class="pill ${tone}">${esc(label)}</span>${live ? `<a class="b sm sec" href="#" data-go="job?id=${j.id}">View listing</a>` : ""}</div></div>
<div class="stats">${statTile(s.views, "students viewed")}${statTile(s.clicks, "clicked Apply", s.views ? Math.round(100 * s.clicks / s.views) + "% of viewers" : "")}${statTile(s.messaged, "messaged you")}${statTile(s.candidates, "candidates", stageBits)}</div>
<p class="small faint">Views and Apply clicks are totals. You see who a student is only when they message you, you invite them, or you save them from matches.</p>
<div class="seg" role="tablist" style="margin:18px 0"><a href="#" data-go="hjob?id=${j.id}&amp;tab=matches"${tab === "matches" ? ' class="on" aria-current="page"' : ""}>Ranked matches</a><a href="#" data-go="hjob?id=${j.id}&amp;tab=candidates"${tab === "candidates" ? ' class="on" aria-current="page"' : ""}>Candidates (${cands.length})</a></div>${content}`;
};

function exportData() {
  const u = me(), d = {account: {email: u.email, role: u.role}, student_profile: SP(u.id) || null, employer_profile: EP(u.id) || null,
    messages_sent: S.convos.flatMap(c => c.messages.filter(m => m.from === u.id).map(m => ({conversation: c.id, body: m.body, status: m.status}))),
    feed_posts: S.posts.filter(p => p.author === u.id).map(p => ({kind: p.kind, body: p.body, status: p.status})), resume_versions: S.versions.filter(v => v.user === u.id).map(v => v.name)};
  return JSON.stringify(d, (k, v) => v instanceof Set ? [...v] : v, 2);
}
function canView(viewer, sid) {
  if (viewer.id === sid) return [true, true, true];
  const p = SP(sid); if (!studentReady(p)) return [false, false, false];
  if (viewer.role === "student") return [true, false, false];
  if (!approvedEmp(viewer.id)) return [false, false, false];
  const talking = S.convos.some(c => c.student === sid && c.employer === viewer.id && !c.blocked_by);
  return p.visible || talking ? [true, true, !!p.share_resume] : [false, false, false];
}
P.u = () => {
  if (!me()) return needLogin("profiles");
  const id = Number(S.route.q.id), [basics, links, resume] = canView(me(), id);
  if (!basics) return '<p class="empty" style="margin:40px 0">That profile isn\'t available.</p>';
  const p = SP(id), owner = id === me().id;
  const msg = isEmployer() && p.allow_messages ? `<a class="b sm" href="#" data-go="newmsg?to=${id}">${icon("chat", 16)} Message</a>` : "";
  // Other students see the basics only; approved employers also see experience, education and projects (like Handshake).
  return `<a class="back" href="#" data-go="${isEmployer() ? "talent" : "feed"}">← Back</a>` + profileHtml(p, {owner, showLinks: links, showResume: resume, messageBtn: msg, showSections: owner || isEmployer()});
};
P.company = () => {
  if (!me()) return needLogin("company pages");
  const id = Number(S.route.q.id), p = EP(id);
  if (!p || (p.status !== "approved" && id !== me().id)) return '<p class="empty" style="margin:40px 0">That organization isn\'t available.</p>';
  const jobs = approvedJobs().filter(j => j.employer_id === id);
  return '<a class="back" href="#" data-go="jobs">← Jobs</a>' + employerCard(p) + (isStudent() && p.status === "approved" ? `<div class="row" style="margin-top:12px"><a class="b" href="#" data-go="newmsg?to=${id}">${icon("chat", 16)} Message ${esc(p.company)}</a></div>` : "") +
    `<h3 class="sec">Open listings</h3>${jobs.map(j => jobCard(j)).join("") || '<div class="empty">No open listings right now.</div>'}`;
};
P.talent = () => {
  if (!isEmployer()) return needLogin("the student directory", "employer");
  const head = pageHead("Find students", "FSU students who chose to be visible to approved employers. Reach out about real roles only; every message is scanned.", "Talent");
  if (!approvedEmp(me().id)) return head + banner("info", "The student directory opens once a reviewer approves your organization.") + '<a class="b" href="#" data-go="admin">Open the reviewer view</a>';
  const q = (S.route.q.q || "").trim().toLowerCase().slice(0, 80), skill = S.route.q.skill || "";
  const res = Object.keys(S.students).map(Number).filter(id => { const p = SP(id); if (!p.visible || !studentReady(p) || !U(id)) return false;
    const hay = [p.display_name, p.major, p.minor, p.headline, p.bio, (p.skills || []).join(" "), (p.interests || []).join(" ")].join(" ").toLowerCase();
    return (!q || q.split(/\s+/).every(w => hay.includes(w))) && (!skill || (p.skills || []).includes(skill) || (p.resume_text || "").toLowerCase().includes(skill.toLowerCase())); });
  const chips = N.POPULAR.slice(0, 14).map(s => `<a class="chipf${skill === s ? " active" : ""}" href="#" data-go="talent?${q ? "q=" + encodeURIComponent(q) + "&amp;" : ""}skill=${encodeURIComponent(s)}">${esc(s)}</a>`).join("");
  return head + `<form class="searchbar" id="talentForm"><input name="q" value="${esc(q)}" placeholder="Search major, skill or interest" aria-label="Search students"><button type="submit">Search</button></form><div class="filter-row"><span class="label">Skill</span>${chips}</div>
<div class="results-head">${plural(res.length, "student")}</div>` + (res.map(id => { const p = SP(id);
    return `<div class="card lift"><div class="row between" style="align-items:flex-start">${person(id)}${p.allow_messages ? `<a class="b sm" href="#" data-go="newmsg?to=${id}">Message</a>` : ""}</div>${p.headline ? `<p style="margin-top:8px">${esc(p.headline)}</p>` : ""}<div class="skills" style="margin-top:10px">${(p.skills || []).slice(0, 8).map(s => `<span class="pill">${esc(s)}</span>`).join("")}</div></div>`; }).join("") || '<div class="empty">No students match yet.</div>');
};
function needLogin(what, role) {
  return pageHead("Log in to use " + what) + `<div class="row"><a class="b" href="#" data-do="${role === "employer" ? "as-employer" : "as-student"}">Explore as a sample ${role === "employer" ? "employer" : "student"}</a><a class="b sec" href="#" data-go="login?role=${role || "student"}">Log in</a></div>`;
}
function needStudent(what) {
  if (!me()) return needLogin(what);
  return pageHead("That page is for FSU students") + banner("info", `Students use ${what}. Switch to the sample student from the demo bar to try it.`) + '<a class="b" href="#" data-do="as-student">Switch to the sample student</a>';
}

// ---- trust pages ----
P.about = () => `${pageHead("About NoleCareerShield")}<div class="prose"><p>Students get targeted by fake job offers constantly: check-cashing schemes, money-mule "recruiters", and pay-to-work training programs. NoleCareerShield is a job board built around one question: <b>is this safe to respond to?</b></p>
<h3>How a listing gets on the board</h3><ul><li>Every submission is scored by an open, rule-based scam detector. Each rule that fires is explained in plain language, so the score is never a black box.</li><li>Every submission then waits for a human reviewer. Nothing is published automatically, no matter how clean the score.</li><li>Approved listings show their verdict. Listings that tripped signals are labeled and explain why.</li></ul>
<h3>Beyond the board</h3><ul><li><b>Profiles</b> that students control, including whether approved employers can find them.</li><li><b>Messaging</b> between students and reviewed employers, with every message scanned for scam signs.</li><li><b>A job assistant</b> that answers in plain words and only suggests listings that passed review.</li><li><b>A resume studio</b> that scores a resume, rewrites weak lines without inventing anything, and tailors it to a job.</li><li><b>A scam checker</b> for any message a student receives, here or anywhere else.</li><li><b>An FSU-only feed</b> where employer posts must be opportunities or advice for FSU students.</li></ul>
<h3>What this is not</h3><p>A verified badge is not a guarantee. Always confirm an employer through their own website before sharing personal information. This is an independent student project and is not affiliated with Florida State University.</p></div>`;
P.privacy = () => `${pageHead("Privacy")}<div class="prose"><p>Short version: browsing is anonymous, you choose what goes on your profile and who sees it, and you can download or delete everything at any time.</p>
<h3>Students</h3><ul><li>A student account needs a confirmed @fsu.edu address and a password, stored as a salted hash. No student ID, date of birth or SSN.</li><li>Your profile holds only what you type in. Your resume is private unless you share it with approved employers.</li><li>Employers see your profile only if a reviewer approved them and you chose to be visible or are already talking with them. They see your experience, education and projects; other students see only your name, school, headline and skills.</li><li>If you upload a resume, we can fill your profile sections from it. Nothing is added that isn't in your resume, and you can edit or delete every entry.</li><li>Your fit score for a job is worked out when you open it. If you're visible to approved employers, they can see how well you fit their listings: the same score and evidence you see.</li><li>We count which listings students open and whether they press Apply, so employers see totals. They never see who viewed or clicked.</li><li>If you message an employer about a listing, or they invite you or save you from their matches, you appear in that employer's candidate list for it, where they can add a stage and a private note.</li></ul>
<h3>Messages and the feed</h3><ul><li>Messages are only between students and approved employers, and every one is scanned when sent. Messages that match scam-only patterns are held for a reviewer.</li><li>Email notifications never include message text.</li><li>Only signed-in FSU students and approved employers can read or post on the feed.</li></ul>
<h3>AI features</h3><ul><li>On the live site the assistant, resume tools and scam checker's second opinion can use Claude. Text is sent only when you use one of those features. This demo runs everything in your browser and sends nothing.</li></ul></div>`;
P.report = () => `${pageHead("Report a listing")}<div class="prose"><p>See something that looks like a scam? Use the Report button on any message or feed post, or email the site operator with the listing title and company. Reports are reviewed by a person.</p><p>If you already sent money or personal information, contact your bank and report it to the FTC at reportfraud.ftc.gov.</p></div>`;

// ---- accounts ----
const COMMON = ["password", "passw", "passwd", "letmein", "welcome", "qwerty", "qwertyuiop", "admin", "administrator", "iloveyou", "monkey", "dragon", "football", "baseball", "seminoles", "seminole", "noles", "gonoles", "floridastate", "tallahassee", "fsu", "changeme", "abcdef", "abcdefgh", "trustno", "sunshine", "princess"];
const EMAIL_RE = /^[^@\s<>"',;:\\]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?\.[A-Za-z]{2,}$/;
const PW_CHECKS = [["8+ characters", "len", p => p.length >= 8], ["A capital letter", "upper", p => /[A-Z]/.test(p)], ["A number", "num", p => /[0-9]/.test(p)], ["A symbol (! ? # $ %)", "sym", p => /[!-\/:-@\[-`{-~]/.test(p)]];
function pwProblems(pw, email) {
  const out = PW_CHECKS.filter(c => !c[2](pw)).map(c => c[0].toLowerCase());
  if (!out.length) { const core = pw.replace(/[^A-Za-z]/g, "").toLowerCase(), local = (email || "").split("@")[0].toLowerCase();
    if (COMMON.includes(core) || (local.length >= 4 && pw.toLowerCase().includes(local))) out.push("something less guessable (not a common word or part of your email)"); }
  return out;
}
const pwText = p => "Your password needs " + (p.length > 1 ? p.slice(0, -1).join(", ") + " and " : "") + p[p.length - 1] + ".";
const findUser = (email, role) => S.users.find(u => u.email === email && u.role === role);
function mail(to, subject, body, link) { S.inbox.unshift({to, subject, body, link}); }
function newToken(u, purpose) { const t = "t" + (++S.tokN) + Math.random().toString(36).slice(2, 8); for (const k in S.tokens) if (S.tokens[k].uid === u.id && S.tokens[k].purpose === purpose) S.tokens[k].used = true; S.tokens[t] = {uid: u.id, purpose, used: false}; return t; }
function sendVerify(u) { mail(u.email, "Confirm your NoleCareerShield account", `Confirm your email to finish creating your ${u.role} account. The link works for 24 hours.\n\nIf you did not sign up, ignore this email and nothing will happen.`, {label: "Open confirmation link", go: "verify?t=" + newToken(u, "verify")}); }
const okNext = n => /^(?:post|jobs|job-\d+)$/.test(n || "") ? n : "";
const authTabs = (role, kind, nx) => `<div class="tabs">${["student", "employer"].map(r => `<a href="#" data-go="${kind}?role=${r}${nx}"${r === role ? ' class="active"' : ""}>${r === "student" ? "Student" : "Employer"}</a>`).join("")}</div>`;
const pwField = (id, name, label, check, forgot) => `<div class="form-field"><div class="label-row"><label for="${id}">${label}</label>${forgot ? `<a class="forgot" href="#" data-go="forgot?role=${forgot}">Forgot password?</a>` : ""}</div><div class="pwbox"><input id="${id}" type="password" name="${name}" required maxlength="128"${check ? " data-pwcheck" : ""}><button type="button" class="showpw" data-do="show">Show</button></div></div>`;
const RULES_LIST = `<ul class="rules" aria-label="Password requirements">${PW_CHECKS.map(c => `<li data-rule="${c[1]}">${c[0]}</li>`).join("")}</ul>`;
const auth = (title, inner, sub) => `<div class="auth"><h2 class="auth-title">${title}</h2>${sub ? `<p class="auth-sub">${sub}</p>` : ""}${inner}</div>`;
P.login = () => {
  const q = S.route.q, role = q.role === "employer" ? "employer" : "student", next = okNext(q.next) || (role === "employer" && S.pendingDraft ? "post" : ""), nx = next ? "&amp;next=" + next : "";
  const note = S.flash ? takeFlash() : role === "employer" && S.pendingDraft ? banner("info", "Log in or create an employer account to send your listing. It's saved and sent for review automatically once you're in.") : "";
  return auth("Log in", `${authTabs(role, "login", nx)}${note}<form id="loginForm" data-role="${role}" data-next="${next}">
<div class="form-field"><label for="f-email">Email</label><input id="f-email" type="email" name="email" required autocomplete="username" placeholder="${role === "student" ? "you@fsu.edu" : "you@company.com"}"></div>${pwField("f-password", "password", "Password", false, role)}
<button class="submit-btn wide" type="submit">Log in</button></form><div class="or"><span>Or</span></div><a class="outline-btn" href="#" data-go="signup?role=${role}${nx}">Create ${role === "student" ? "a student" : "an employer"} account</a>
<p class="fine">Demo accounts: <b>jordan@fsu.edu</b> (student) and <b>pat@garnetanalytics.example</b> (employer), password <b>${PW}</b>.</p>`);
};
P.signup = () => {
  const q = S.route.q, role = q.role === "employer" ? "employer" : "student", next = okNext(q.next) || (role === "employer" && S.pendingDraft ? "post" : ""), nx = next ? "&amp;next=" + next : "";
  return auth("Sign up", `${authTabs(role, "signup", nx)}${takeFlash()}<form id="signupForm" data-role="${role}" data-next="${next}">
<div class="form-field"><label for="f-email">Email</label><input id="f-email" type="email" name="email" required autocomplete="username" placeholder="${role === "student" ? "you@fsu.edu" : "you@company.com"}"></div>
${pwField("f-password", "password", "Password", true)}${RULES_LIST}${pwField("f-password2", "password2", "Confirm password")}
<button class="submit-btn wide" type="submit">Create account</button></form><div class="or"><span>Or</span></div><a class="outline-btn" href="#" data-go="login?role=${role}${nx}">I already have an account</a>`,
    role === "student" ? "Use your @fsu.edu email. We send a link to confirm it." : "Any email works. We send a link to confirm it before you can post.");
};
P.checkmail = () => auth("Check your email", `${banner("info", `If that address can receive an account, we just sent a confirmation link to ${esc(S.route.q.email || "")}. It works for 24 hours.`, true)}<a class="outline-btn" href="#" data-go="inbox">Open the demo inbox</a><p class="fine">On the real site it lands in your own mailbox.</p>`);
P.verify = () => {
  const rec = S.tokens[S.route.q.t];
  if (!rec || rec.used || rec.purpose !== "verify") return auth("Link not valid", banner("warning", "That link has expired or was already used.") + '<a class="outline-btn" href="#" data-go="login">Log in</a>');
  return auth("Confirm your email", `${takeFlash()}<form id="verifyForm" data-t="${esc(S.route.q.t)}">${pwField("f-password", "password", "Password")}<button class="submit-btn wide" type="submit">Confirm my email</button></form>`, "Enter the password you chose when you signed up. This makes sure the account is really yours.");
};
P.forgot = () => { const role = S.route.q.role === "employer" ? "employer" : "student";
  return auth("Forgot password", `<form id="forgotForm" data-role="${role}"><div class="form-field"><label for="f-email">Email</label><input id="f-email" type="email" name="email" required autocomplete="username"></div><button class="submit-btn wide" type="submit">Send reset link</button></form><p class="fine"><a href="#" data-go="login?role=${role}">Back to log in</a></p>`, "Enter your email and we will send a link to choose a new password."); };
P.reset = () => {
  const rec = S.tokens[S.route.q.t];
  if (!rec || rec.used || rec.purpose !== "reset") return auth("Link not valid", banner("warning", "That link has expired or was already used.") + '<a class="outline-btn" href="#" data-go="login">Log in</a>');
  return auth("Choose a new password", `${takeFlash()}<form id="resetForm" data-t="${esc(S.route.q.t)}">${pwField("f-password", "password", "New password", true)}${RULES_LIST}${pwField("f-password2", "password2", "Confirm new password")}<button class="submit-btn wide" type="submit">Save new password</button></form>`);
};
P.inbox = () => pageHead("Demo inbox", "On the real site these go to the person's own mailbox. Here they're shown so you can click the links.", "Demo") +
  (S.inbox.map(m => `<div class="card"><div class="small faint">To: ${esc(m.to)}</div><b>${esc(m.subject)}</b><pre style="white-space:pre-wrap;font:13px/1.55 var(--mono);background:var(--sunk);padding:10px 12px;border-radius:8px;margin:10px 0">${esc(m.body)}</pre>${m.link ? `<a class="b sm" href="#" data-go="${esc(m.link.go)}">${esc(m.link.label)}</a>` : ""}</div>`).join("") || '<div class="empty">No mail yet. Create an account and the confirmation email appears here.</div>');

// ---- reviewer ----
const ADMIN_TABS = [["admin", "Listings"], ["aemployers", "Employers"], ["aposts", "Feed"], ["amessages", "Held messages"], ["areports", "Reports"]];
function adminCounts() { return {admin: S.jobs.filter(j => j.review_status === "pending").length, aemployers: Object.values(S.employers).filter(p => p.status === "pending").length,
  aposts: S.posts.filter(p => ["pending", "held"].includes(p.status)).length, amessages: S.convos.reduce((n, c) => n + c.messages.filter(m => m.status === "held").length, 0), areports: S.reports.filter(r => !r.resolved).length}; }
function adminPage(title, active, body) {
  if (!S.admin) return `${pageHead("Reviewer sign-in", "The review queues are restricted. In this demo any password works.")}<form id="adminLogin" class="card" style="max-width:440px"><div class="form-field"><label for="a-pw">Password</label><input id="a-pw" type="password" name="password" required maxlength="200" autocomplete="off"></div><button class="submit-btn" type="submit">Sign in</button></form>`;
  const c = adminCounts();
  return `<h2 class="page">${esc(title)}</h2><div class="admin-tabs seg">${ADMIN_TABS.map(([k, t]) => `<a href="#" data-go="${k}"${k === active ? ' class="on"' : ""}>${t}${c[k] ? " · " + c[k] : ""}</a>`).join("")}<a href="#" data-go="live"${active === "live" ? ' class="on"' : ""}>Live listings</a></div>${body}<p style="margin-top:18px"><button class="linkbtn" type="button" data-do="admin-out">Sign out of the reviewer view</button></p>`;
}
const findingsHtml = fs => fs.filter(f => f.severity !== "note").map(f => `<div class="finding ${esc(f.severity)}"><b>${esc(f.title)}</b><br>${esc(f.why)}</div>`).join("");
P.admin = () => {
  const list = S.jobs.filter(j => j.review_status === "pending").slice().reverse();
  const rows = S.jobs.filter(j => ["legit", "scam", "lead_gen"].includes(j.review_label) && !j.seedApproved);
  let agree = 0, missed = 0, fa = 0; rows.forEach(j => { const flagged = j.scam_status !== "clear", bad = j.review_label !== "legit"; if (flagged === bad) agree++; else if (bad) missed++; else fa++; });
  const stats = rows.length ? `<p class="lead" style="font-size:13px">Detector vs your decisions: ${rows.length} labeled${rows.length < 10 ? " so far. Too few to judge; every decision is training data for the next rule update." : `, agreed on ${Math.round(100 * agree / rows.length)}%. Missed ${missed}; flagged ${fa} you approved.`}</p>` : "";
  return adminPage("Review queue", "admin", `${stats}<p class="lead">${plural(list.length, "submission")} waiting. The scam score is advisory; you decide what publishes.</p>` + (list.map(j => `<div class="rev-card"><div class="row between" style="align-items:flex-start"><div><div class="job-title">${esc(j.title)}</div><div class="job-co">${esc(j.company)}</div></div><span class="rev-score ${esc(j.scam_status)}">${esc(scorePill(j))}</span></div>
<div class="job-meta" style="margin-top:10px"><span class="chip">${esc(j.category)}</span><span class="chip">${esc(cap(j.work_type))}</span>${j.location ? `<span class="chip">${esc(j.location)}</span>` : ""}</div>
${findingsHtml(j.findings) ? `<div style="margin:12px 0">${findingsHtml(j.findings)}</div>` : '<p class="small muted" style="margin:10px 0">No scam signals fired.</p>'}
<div class="detail-desc" style="font-size:14px;max-height:140px;overflow:auto;background:var(--sunk);padding:10px 12px;border-radius:8px">${esc(j.description)}</div>${j.apply_url ? `<p class="small muted" style="word-break:break-all">Apply: ${esc(j.apply_url)}</p>` : ""}
<div class="rev-actions"><button class="btn-approve" type="button" data-act="approve" data-id="${j.id}">Approve &amp; publish</button><button class="btn-reject" type="button" data-act="reject" data-reason="scam" data-id="${j.id}">Reject: scam</button><button class="btn-reject" type="button" data-act="reject" data-reason="lead_gen" data-id="${j.id}">Reject: aggregator</button><button class="btn-reject" type="button" data-act="reject" data-reason="other" data-id="${j.id}">Reject: other</button></div></div>`).join("") || '<div class="empty">Nothing waiting for review.</div>'));
};
P.live = () => adminPage("Live listings", "live", approvedJobs().slice().reverse().map(j => `<div class="rev-card"><div class="row between"><div><div class="job-title">${esc(j.title)}</div><div class="job-co">${esc(j.company)}</div></div><div class="rev-actions" style="margin-top:0"><button class="btn-reject" type="button" data-act="remove" data-reason="scam" data-id="${j.id}">Remove: scam</button><button class="btn-reject" type="button" data-act="remove" data-reason="other" data-id="${j.id}">Remove: other</button></div></div></div>`).join("") || '<div class="empty">No live listings.</div>');
function domainNote(email, site) {
  const ed = email.split("@").pop().toLowerCase(), host = ((/^https?:\/\/([^\/?#]+)/i.exec(site || "") || [])[1] || "").toLowerCase().replace(/^www\./, "");
  if (["gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com", "aol.com"].includes(ed)) return `<span class="pill warn">Personal email (@${esc(ed)})</span>`;
  if (host && (ed === host || ed.endsWith("." + host) || host.endsWith("." + ed))) return '<span class="pill ok">✓ Email domain matches website</span>';
  return `<span class="pill warn">Email @${esc(ed)} ≠ website ${esc(host || "?")}</span>`;
}
P.aemployers = () => adminPage("Employers", "aemployers", Object.keys(S.employers).map(Number).filter(id => S.employers[id].status === "pending").map(id => { const p = EP(id), u = U(id);
  return `<div class="rev-card"><div class="row between" style="align-items:flex-start"><div><div class="job-title">${esc(p.company)}</div><div class="job-co">${esc(u.email)} · ${esc(p.contact_name || "")}, ${esc(p.contact_title || "")}</div></div>${domainNote(u.email, p.website)}</div>
<p style="margin-top:10px">${esc(p.about)}</p><p class="small muted" style="margin-top:6px"><b>FSU connection:</b> ${esc(p.fsu_connection)}</p><p class="small muted">Website: ${esc(p.website)}</p>
<div class="rev-actions"><button class="btn-approve" type="button" data-do="emp-approve" data-id="${id}">Approve</button><button class="btn-reject" type="button" data-do="emp-reject" data-id="${id}" data-note="We couldn't confirm the organization from its website and email.">Reject: can't verify</button><button class="btn-reject" type="button" data-do="emp-reject" data-id="${id}" data-note="We couldn't see how the organization hires or supports FSU students.">Reject: not FSU-related</button></div></div>`; }).join("") || '<div class="empty">No employers waiting.</div>');
P.aposts = () => adminPage("Feed review", "aposts", S.posts.filter(p => ["pending", "held"].includes(p.status)).map(p => `<div class="rev-card"><div class="row between">${person(p.author, false)}<span class="pill warn">${p.status === "pending" ? "Employer post, needs approval" : "Held: scanner flags or reports"}</span></div>
<p class="small" style="margin-top:6px">Type: ${esc(KINDS[p.kind])} · scan: ${esc(p.scan)}${p.rel ? ` · FSU signals: ${esc(p.rel.signals.join(", ") || "none")}` : ""}</p>${p.flags.map(f => `<div class="finding warning"><b>${esc(f)}</b></div>`).join("")}
<div class="detail-desc" style="font-size:14px;background:var(--sunk);padding:10px 12px;border-radius:8px">${esc(p.body)}</div>${p.link ? `<p class="small">Link: ${esc(p.link)}</p>` : ""}
<div class="rev-actions"><button class="btn-approve" type="button" data-do="post-publish" data-id="${p.id}">Publish</button><button class="btn-reject" type="button" data-do="post-reject" data-id="${p.id}">Reject</button></div></div>`).join("") || '<div class="empty">Nothing waiting.</div>');
P.amessages = () => adminPage("Held messages", "amessages", S.convos.flatMap(c => c.messages.filter(m => m.status === "held").map(m => `<div class="rev-card"><div class="row between"><div class="small">From <b>${esc(who(m.from)[0])}</b> to <b>${esc(who(m.from === c.student ? c.employer : c.student)[0])}</b></div><span class="rev-score held">${esc(m.band)}</span></div>
${m.findings.map(f => `<div class="finding critical"><b>${esc(f)}</b></div>`).join("")}<div class="detail-desc" style="font-size:14px;background:var(--sunk);padding:10px 12px;border-radius:8px">${esc(m.body)}</div>
<div class="rev-actions"><button class="btn-approve" type="button" data-do="msg-deliver" data-c="${c.id}" data-id="${m.id}">Deliver anyway</button><button class="btn-reject" type="button" data-do="msg-remove" data-c="${c.id}" data-id="${m.id}">Remove</button>${U(m.from).role === "employer" ? `<button class="btn-reject" type="button" data-do="emp-suspend" data-id="${m.from}">Remove and suspend sender</button>` : ""}</div></div>`)).join("") || '<div class="empty">No held messages.</div>');
P.areports = () => adminPage("Reports", "areports", S.reports.filter(r => !r.resolved).map((r, i) => `<div class="rev-card"><div class="row between"><b>${esc(r.what)}</b><span class="small faint">${ago(r.at)}</span></div><p class="small muted">Reported by ${esc(who(r.by)[0])}</p><div class="detail-desc" style="font-size:14px;background:var(--sunk);padding:10px 12px;border-radius:8px">${esc(r.text)}</div>
<div class="rev-actions"><button class="btn-approve" type="button" data-do="report-resolve" data-i="${S.reports.indexOf(r)}">Resolve</button></div></div>`).join("") || '<div class="empty">No open reports. Report a message or feed post to see one here.</div>');

// ---------------- router ----------------
function render(keepScroll) {
  nav();
  const name = S.route.name, fn = P[name] || P.home;
  let out = fn(); if (out === null) return;
  const hero = out && out.hero ? out.hero : "", body = out && out.body !== undefined ? out.body : out;
  const inApp = me() && name in APP_PAGES && !(name === "home" && !me());
  const main = $("#app");
  if (inApp) main.innerHTML = `<div class="app">${sidebar(APP_PAGES[name])}<main class="main" id="main"><div class="wrap">${body}</div>${FOOTER}</main></div>`;
  else main.innerHTML = `${hero}<div class="wrap"><main id="main">${body}</main></div>${FOOTER}`;
  if (!keepScroll) window.scrollTo(0, 0);
  if (S.scrollTo) { const el = document.getElementById(S.scrollTo); S.scrollTo = null; if (el) el.scrollIntoView({block: "start"}); }
  const th = $("#thread"); if (th) th.scrollTop = th.scrollHeight;
  const lg = $("#log"); if (lg) lg.scrollTop = lg.scrollHeight;
}
function go(spec) {
  const hash = spec.indexOf("#"); if (hash >= 0) { S.scrollTo = spec.slice(hash + 1); spec = spec.slice(0, hash); }
  const i = spec.indexOf("?"), name = i < 0 ? spec : spec.slice(0, i), q = {};
  if (i >= 0) new URLSearchParams(spec.slice(i + 1).replace(/&amp;/g, "&")).forEach((v, k) => q[k] = v);
  ["id", "m", "c", "to", "job", "step"].forEach(k => { if (q[k] !== undefined) q[k] = Number(q[k]); });
  S.route = {name, q}; if (name !== "post") S.draft = null;
  if (name !== "resume") { S.tailor = null; S.bulletOut = null; }
  if (name !== "item") S.itemDraft = null;
  render();
}
const FOOTER = `<footer>Every listing is scanned for scam signals and reviewed by a human before it appears. A verified badge is not a guarantee; always confirm an employer through their own website before sharing personal information.
<span class="tm"><a href="#" data-go="about">About</a> · <a href="#" data-go="privacy">Privacy</a> · <a href="#" data-go="report">Report a listing</a> · <a href="#" data-go="scam">Scam check</a></span>
<span class="tm">An independent student project. Not affiliated with, sponsored by, or endorsed by Florida State University; uses no university trademarks or logos.</span></footer>`;
function signIn(email, role) { S.session = findUser(email, role); S.chat = null; }
function afterLogin(next) {
  const u = me();
  if (u.role === "employer" && S.pendingDraft) { submitDraft(); return go("posted"); }
  const n = okNext(next);
  if (u.role === "student" && !(SP(u.id) || {}).setup_step) return go("setup?step=1");
  if (u.role === "employer" && !(EP(u.id) || {}).company) return go("setup?step=1");
  if (n === "post" && u.role === "employer") return go("post");
  if (/^job-\d+$/.test(n)) return go("job?id=" + n.slice(4));
  go("home");
}
function submitDraft() {
  const d = S.pendingDraft; S.pendingDraft = null; if (!d) return;
  const j = Object.assign({id: S.nextJob++, employer_id: me().id, age_days: 0, review_status: "pending", review_label: null}, d);
  scoreJob(j); S.jobs.push(j);
  mail(me().email, "We received your listing", `We received your listing "${d.title}". It has been scanned, and a person reviews every listing before it appears on the board.`, null);
}

// ---------------- events ----------------
document.addEventListener("click", e => {
  const ap = e.target.closest("[data-apply]"); if (ap && isStudent()) { const k = Number(ap.dataset.apply); (S.clicks[k] = S.clicks[k] || new Set()).add(me().id); return; }
  const a = e.target.closest("[data-go]"); if (a) { e.preventDefault(); go(a.dataset.go); return; }
  const b = e.target.closest("[data-act]");
  if (b && S.admin) { const j = S.jobs.find(x => x.id === Number(b.dataset.id)); if (!j) return; const act = b.dataset.act; j.seedApproved = false;
    if (act === "approve" && j.review_status === "pending") { j.review_status = "approved"; j.review_label = "legit"; }
    else if (act === "reject" && j.review_status === "pending") { j.review_status = "rejected"; j.review_label = b.dataset.reason; }
    else if (act === "remove" && j.review_status === "approved") { j.review_status = "removed"; j.review_label = b.dataset.reason; }
    render(true); return; }
  const d = e.target.closest("[data-do]"); if (!d) return; e.preventDefault();
  const k = d.dataset.do, id = Number(d.dataset.id);
  const c = S.route.q.c ? S.convos.find(x => x.id === S.route.q.c) : null;
  const acts = {
    "as-student": () => { signIn("jordan@fsu.edu", "student"); go("home"); },
    "as-employer": () => { signIn("pat@garnetanalytics.example", "employer"); go("home"); },
    "as-reviewer": () => { S.admin = true; go("admin"); },
    logout: () => { S.session = null; go("home"); },
    "admin-out": () => { S.admin = false; go("home"); },
    reset: () => { S.timers.forEach(clearTimeout); reset(); render(); },
    show: () => { const i = d.parentElement.querySelector("input"); i.type = i.type === "password" ? "text" : "password"; d.textContent = i.type === "password" ? "Show" : "Hide"; },
    sample: () => { const s = SAMPLES[Number(d.dataset.i)]; go(`scam?run=1&text=${encodeURIComponent(s[1])}&sender=${encodeURIComponent(s[2])}`); },
    ask: () => ask(SUGG[Number(d.dataset.i)]),
    "apply-rewrite": () => { const r = S.lastRewrites[Number(d.dataset.i)], p = SP(me().id); if (r && p.resume_text.includes(r.text)) p.resume_text = p.resume_text.replace(r.text, r.rewrite); flash("verified", "Rewrite applied. Fill in any [placeholder] with your real numbers."); render(true); },
    "sample-resume": () => { const p = SP(me().id); p.resume_text = RESUME; p.resume_name = "Sample resume"; if (!(p.items || []).length) importResume(p); render(); },
    "save-cand": () => { const j = S.jobs.find(x => x.id === S.route.q.id && x.employer_id === me().id), p = SP(id); if (j && p && p.visible) addCandidate(j.id, id, me().id, "saved"); render(true); },
    "import-resume": () => { const n = importResume(SP(me().id)); flash(n ? "verified" : "info", n ? `Added ${n} entr${n === 1 ? "y" : "ies"} from your resume. Check them over and edit anything that's off.` : "Your profile already has everything your resume shows."); render(true); },
    "del-item": () => { const p = SP(me().id), it = (p.items || []).find(i => i.id === id); p.items = (p.items || []).filter(i => i.id !== id); flash("verified", "Entry deleted."); go("profile" + (it ? "#" + it.kind : "")); },
    "to-tailor": () => { const el = document.getElementById("tailor"); if (el) el.scrollIntoView({behavior: "smooth", block: "start"}); },
    copy: () => { const t = d.dataset.text || ""; try { navigator.clipboard.writeText(t).then(() => { d.textContent = "Copied"; }, () => {}); } catch (x) { /* clipboard unavailable */ } },
    "fill-sample": () => { $("#p-paste").value = RESUME; },
    "copy-resume": () => { const t = $("#r-text"); try { navigator.clipboard.writeText(t.value).then(() => { d.textContent = "Copied"; }, () => t.select()); } catch (x) { t.select(); } },
    "use-version": () => { const v = S.versions.find(x => x.id === id); if (v) { SP(me().id).resume_text = v.body; flash("verified", `"${v.name}" is now your main resume.`); } render(); },
    "del-version": () => { S.versions = S.versions.filter(x => x.id !== id); render(true); },
    block: () => { c.blocked_by = me().id; render(true); }, unblock: () => { c.blocked_by = null; render(true); },
    archive: () => { c.hidden[me().id] = true; go("messages"); },
    "report-convo": () => { const last = c.messages.filter(m => m.from !== me().id).pop(); S.reports.push({what: "Conversation reported", by: me().id, text: last ? last.body : "(no messages)", at: NOW()}); flash("verified", "Reported. A reviewer will look at this conversation. You can also block the sender."); render(true); },
    helpful: () => { const p = S.posts.find(x => x.id === id); p.helpful.has(me().id) ? p.helpful.delete(me().id) : p.helpful.add(me().id); render(true); },
    comments: () => { S.openComments = S.openComments === id ? null : id; render(true); },
    "report-post": () => { const p = S.posts.find(x => x.id === id); if (!p.reports.has(me().id)) { p.reports.add(me().id); S.reports.push({what: "Feed post reported", by: me().id, text: p.body, at: NOW()}); if (p.reports.size >= 3) p.status = "held"; } render(true); },
    "del-post": () => { S.posts = S.posts.filter(x => x.id !== id); render(true); },
    export: () => { S.showExport = !S.showExport; render(true); },
    "emp-approve": () => { EP(id).status = "approved"; mail(U(id).email, "Your organization was approved", "A reviewer approved your organization. You can now message students, browse the directory and post to the FSU feed.", null); render(true); },
    "emp-reject": () => { EP(id).status = "rejected"; EP(id).status_note = d.dataset.note; render(true); },
    "emp-suspend": () => { EP(id).status = "suspended"; S.convos.forEach(cv => cv.messages.forEach(m => { if (m.from === id && m.status === "held") m.status = "removed"; })); render(true); },
    "post-publish": () => { S.posts.find(x => x.id === id).status = "published"; render(true); },
    "post-reject": () => { S.posts.find(x => x.id === id).status = "rejected"; render(true); },
    "msg-deliver": () => { const cv = S.convos.find(x => x.id === Number(d.dataset.c)); cv.messages.find(m => m.id === id).status = "delivered"; render(true); },
    "msg-remove": () => { const cv = S.convos.find(x => x.id === Number(d.dataset.c)); cv.messages.find(m => m.id === id).status = "removed"; render(true); },
    "report-resolve": () => { S.reports[Number(d.dataset.i)].resolved = true; render(true); },
    resend: () => { const u = findUser(d.dataset.email, d.dataset.role); if (u && !u.verified) sendVerify(u); go("checkmail?email=" + encodeURIComponent(d.dataset.email)); },
  };
  if (acts[k]) acts[k]();
});
document.addEventListener("input", e => {
  if (e.target.matches("[data-pwcheck]")) { const v = e.target.value; PW_CHECKS.forEach(c => { const li = document.querySelector(`[data-rule="${c[1]}"]`); if (li) li.className = c[2](v) ? "ok" : ""; }); }
  if (e.target.id === "q" || e.target.id === "m-body") { e.target.style.height = "auto"; e.target.style.height = Math.min(e.target.scrollHeight + 2, 180) + "px"; }
});
document.addEventListener("keydown", e => {
  if ((e.target.id === "q" || e.target.id === "m-body") && e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); e.target.form.requestSubmit(); }
});
document.addEventListener("submit", e => {
  e.preventDefault();
  const f = e.target, fd = new FormData(f), g = k => String(fd.get(k) || "").trim(), many = k => fd.getAll(k).map(String);
  const id = f.id;
  if (id === "searchForm") { const qs = new URLSearchParams(); if (g("search")) qs.set("search", g("search")); if (S.route.q.category) qs.set("category", S.route.q.category); if (S.route.q.work_type) qs.set("work_type", S.route.q.work_type); return go("jobs" + (qs.toString() ? "?" + qs : "")); }
  if (id === "talentForm") return go("talent" + (g("q") ? "?q=" + encodeURIComponent(g("q")) : ""));
  if (id === "adminLogin") { S.admin = true; return go("admin"); }
  if (id === "scamForm") { if (!g("text")) return; return go(`scam?run=1&text=${encodeURIComponent(g("text").slice(0, 8000))}&sender=${encodeURIComponent(g("sender"))}`); }
  if (id === "askForm") { ask(g("q")); return; }
  if (id === "loginForm") {
    const role = f.dataset.role, u = findUser(g("email").toLowerCase(), role);
    if (!u || u.pw !== fd.get("password")) { flash("warning", "The email or password is incorrect."); return go(`login?role=${role}&next=${f.dataset.next}`); }
    if (!u.verified) { flash("warning", `Confirm your email first. We sent you a link when you signed up. <button type="button" class="linkbtn" data-do="resend" data-role="${role}" data-email="${esc(u.email)}">Send me a new confirmation email</button>`, true); return go(`login?role=${role}&next=${f.dataset.next}`); }
    S.session = u; S.chat = null; return afterLogin(f.dataset.next);
  }
  if (id === "signupForm") {
    const role = f.dataset.role, email = g("email").toLowerCase(), pw = String(fd.get("password")), back = t => { flash("warning", t); go(`signup?role=${role}&next=${f.dataset.next}`); };
    if (!EMAIL_RE.test(email)) return back("Enter a valid email address.");
    if (role === "student" && email.split("@").pop() !== "fsu.edu") return back("Student accounts need an @fsu.edu email address.");
    const p = pwProblems(pw, email); if (p.length) return back(pwText(p));
    if (pw !== fd.get("password2")) return back("The two passwords do not match.");
    const u = findUser(email, role);
    if (!u) { const nu = {id: S.nextId++, email, role, pw, verified: false}; S.users.push(nu); sendVerify(nu); }
    else if (!u.verified) { u.pw = pw; sendVerify(u); }
    else mail(email, "You already have a NoleCareerShield account", "Someone (hopefully you) tried to create an account with this address, but one already exists. Log in, or use Forgot password.", null);
    return go("checkmail?email=" + encodeURIComponent(email));
  }
  if (id === "verifyForm") {
    const t = f.dataset.t, rec = S.tokens[t], u = rec && U(rec.uid);
    if (!rec || rec.used || !u) return go("verify?t=" + t);
    if (u.pw !== fd.get("password")) { flash("warning", "That is not the password this account was created with."); return go("verify?t=" + t); }
    rec.used = true; u.verified = true; S.session = u; S.chat = null;
    if (u.role === "employer" && S.pendingDraft) submitDraft();
    flash("verified", "Email confirmed. You're logged in. " + (u.role === "student" ? "Next, set up your profile. It takes about two minutes and powers your job matches." : "Next, set up your company profile. A reviewer approves it before you can message students or post to the feed."));
    return go("setup?step=1");
  }
  if (id === "forgotForm") { const u = findUser(g("email").toLowerCase(), f.dataset.role);
    if (u && u.verified) mail(u.email, "Reset your NoleCareerShield password", "Choose a new password. The link works for one hour and can be used once. If you did not ask for this, ignore this email.", {label: "Open reset link", go: "reset?t=" + newToken(u, "reset")});
    flash("info", "If that address has an account, we sent a reset link. Open the demo inbox."); return go("login?role=" + f.dataset.role); }
  if (id === "resetForm") {
    const t = f.dataset.t, rec = S.tokens[t], u = rec && U(rec.uid); if (!rec || rec.used || !u) return go("reset?t=" + t);
    const p = pwProblems(String(fd.get("password")), u.email); if (p.length) { flash("warning", pwText(p)); return go("reset?t=" + t); }
    if (fd.get("password") !== fd.get("password2")) { flash("warning", "The two passwords do not match."); return go("reset?t=" + t); }
    rec.used = true; u.pw = String(fd.get("password")); if (S.session === u) S.session = null;
    flash("verified", "Password updated. Every device was logged out. Log in with your new password."); return go("login?role=" + u.role);
  }
  if (id === "postForm") {
    const d = {title: g("title"), company: g("company"), category: g("category"), work_type: g("work_type"), location: g("location"), description: g("description"), apply_url: g("apply_url"), contact: ""};
    S.draft = d;
    if (!d.title || !d.company || !d.description) { flash("warning", "Title, company and description are required."); return render(); }
    if (d.apply_url && !/^https?:\/\/[^\s<>"']+$/i.test(d.apply_url)) { flash("warning", "The apply URL must start with http:// or https://."); return render(); }
    S.pendingDraft = d; S.draft = null;
    if (isEmployer()) { submitDraft(); return go("posted"); }
    return go("login?role=employer&next=post");
  }
  // profile setup
  const nameOk = v => /^[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ .'\-]{1,59}$/.test(v) && !v.includes("@");
  const url = (v, host) => { if (!v) return ""; if (!/^https?:\/\//i.test(v)) v = "https://" + v; if (!/^https?:\/\/[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?:[\/?#][^\s<>"']*)?$/.test(v)) return null;
    const h = /^https?:\/\/([^\/?#]+)/i.exec(v)[1].toLowerCase(); return host && !(h === host || h.endsWith("." + host)) ? null : v; };
  const back = (step, msg) => { flash("warning", msg); go("setup?step=" + step); };
  if (id === "setup1") { const p = SP(me().id), n = g("display_name");
    if (!nameOk(n)) return back(1, "Use letters for your name (no emails or links).");
    if (!g("major")) return back(1, "Major is required.");
    Object.assign(p, {display_name: n, pronouns: g("pronouns").slice(0, 24), major: g("major").slice(0, 80), minor: g("minor").slice(0, 80), degree: g("degree"), grad_term: g("grad_term"), headline: g("headline").slice(0, 120), bio: g("bio").slice(0, 600), setup_step: Math.max(p.setup_step || 0, 1)});
    return go("setup?step=2"); }
  if (id === "setup2") { const p = SP(me().id), skills = many("skills").filter(s => N.POPULAR.includes(s));
    g("more_skills").split(",").forEach(r => { const s = N.normalizeSkill(r); if (s && !skills.includes(s) && !/[<>{}]|https?:/.test(s)) skills.push(s); });
    const roles = g("looking_roles").slice(0, 300).split(",").map(x => x.trim().replace(/\s+/g, " ")).filter(x => x && x.length <= 60).slice(0, 8);
    const locs = g("pref_locations").slice(0, 300).split(/[;|]|,(?!\s*[A-Z]{2}\b)/).map(x => x.trim().replace(/\s+/g, " ")).filter(x => x && x.length <= 60).slice(0, 8);
    Object.assign(p, {skills: skills.slice(0, 30), interests: many("interests"), work_types: many("work_types"), job_kinds: many("job_kinds"), looking_roles: roles, pref_locations: locs, setup_step: Math.max(p.setup_step || 0, 2)});
    return go("setup?step=3"); }
  if (id === "setup3") { const p = SP(me().id), li = url(g("linkedin"), "linkedin.com"), web = url(g("website"));
    if (li === null) return back(3, "LinkedIn should be a linkedin.com address."); if (web === null) return back(3, "Website doesn't look like a web address.");
    Object.assign(p, {links: {linkedin: li, website: web}, visible: !!fd.get("visible"), share_resume: !!fd.get("share_resume"), allow_messages: !!fd.get("allow_messages"), setup_step: 3});
    const finish = (text, name) => {
      let added = 0;
      if (text) { p.resume_text = text.slice(0, 20000); p.resume_name = name; if (!(p.skills || []).length) p.skills = N.extractSkills(text).slice(0, 20); if (!(p.items || []).length) added = importResume(p); }
      S.profileNotice = added ? `We filled in ${added} entr${added === 1 ? "y" : "ies"} from your resume. Check them over and edit anything that's off.` : "";
      flash("verified", "Your profile is set up. Every job now shows how well you fit it."); go("profile"); };
    const file = fd.get("resume_file"), paste = g("resume_paste");
    if (file && file.size) { readResumeFile(file).then(t => finish(t, file.name.slice(0, 120)), msg => back(3, String(msg))); return; }
    if (paste) return finish(cleanResumeText(paste), "Pasted text");
    return finish("", ""); }
  if (id === "esetup1") { const p = EP(me().id), web = url(g("website"));
    if (!g("company")) return back(1, "Organization name is required."); if (!web) return back(1, "Website doesn't look like a web address.");
    if (g("about").length < 40) return back(1, "Write at least a couple of sentences about the organization.");
    Object.assign(p, {company: g("company").slice(0, 120), website: web, industry: g("industry"), size: g("size"), location: g("location").slice(0, 120), about: g("about").slice(0, 1500)});
    return go("setup?step=2"); }
  if (id === "esetup2") { const p = EP(me().id);
    if (!g("contact_name") || !g("contact_title") || !g("fsu_connection")) return back(2, "Fill in your name, title and how you work with FSU students.");
    Object.assign(p, {contact_name: g("contact_name"), contact_title: g("contact_title"), fsu_connection: g("fsu_connection").slice(0, 800)});
    if (["draft", "rejected", undefined].includes(p.status)) p.status = "pending";
    return go("profile"); }
  if (id === "deleteForm") {
    if (fd.get("password") !== me().pw) { flash("warning", "That password isn't right, so nothing was deleted."); return go("profile"); }
    const uid = me().id; S.users = S.users.filter(u => u.id !== uid); delete S.students[uid]; delete S.employers[uid];
    S.posts = S.posts.filter(p => p.author !== uid); S.posts.forEach(p => { p.comments = p.comments.filter(c => c.author !== uid); });
    S.convos.forEach(c => { c.messages.forEach(m => { if (m.from === uid) { m.body = ""; m.status = "removed"; } }); if (c.student === uid || c.employer === uid) c.blocked_by = uid; });
    S.versions = S.versions.filter(v => v.user !== uid); S.session = null;
    flash("verified", "Your account is deleted. Your profile, resume, posts and comments are gone, and the messages you sent were blanked."); S.route = {name: "about", q: {}}; return render();
  }
  // messaging
  if (id === "sendForm") { const c = S.convos.find(x => x.id === S.route.q.c), t = g("body"); if (!t || !c || c.blocked_by) return; sendMessage(c, t.slice(0, 4000)); return render(true); }
  if (id === "newMsgForm") { const to = Number(f.dataset.to), job = Number(f.dataset.job), t = g("body"); if (!t) return;
    const [ok, why] = canStart(me(), to); if (!ok) { flash("info", why); return go("messages"); }
    const sid = isStudent() ? me().id : to, eid = isStudent() ? to : me().id;
    const c = S.convos.find(x => x.student === sid && x.employer === eid && x.job === job) || convo(sid, eid, job); sendMessage(c, t.slice(0, 4000)); return go("messages?c=" + c.id); }
  // feed
  if (id === "feedForm") {
    const body = g("body"), kind = g("kind"), link = g("link"); S.feedDraft = {body, kind, link};
    const again = msg => { flash("warning", msg); render(true); };
    if (body.length < 10) return again("Write a little more (at least 10 characters).");
    if (link && !/^(?:https?:\/\/)?[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?:[\/?#][^\s<>"']*)?$/i.test(link)) return again("That link doesn't look like a web address.");
    const full = link && !/^https?:\/\//i.test(link) ? "https://" + link : link;
    let status, rel = null;
    if (isEmployer()) { rel = N.relevance(body, kind, full); if (!rel.ok) return again("This can't go on the FSU feed yet. " + rel.problems.join(" ")); status = "pending"; }
    const p = post(me().id, kind, body, full, "published"); if (isStudent()) status = ["review", "block"].includes(p.scan) ? "held" : "published";
    p.status = status; p.rel = rel; S.posts.push(p); S.feedDraft = null;
    if (status === "pending") flash("info", "Sent for review. A reviewer approves each employer post before it appears. Open the reviewer view to approve it in the demo.");
    else if (status === "held") flash("warning", "Your post matched scam patterns, so it's held for a reviewer before it appears.");
    return render(true);
  }
  if (f.classList.contains("commentForm")) { const p = S.posts.find(x => x.id === Number(f.dataset.id)), t = g("body"); if (!t) return;
    const scan = N.check(t); if (["review", "block"].includes(scan.band)) { S.reports.push({what: "Comment held by the scanner", by: me().id, text: t, at: NOW()}); flash("warning", "That comment matched scam patterns, so a reviewer will check it first."); }
    else p.comments.push({author: me().id, body: t.slice(0, 500), at: NOW()});
    return render(true); }
  // resume
  if (id === "resumeUpload") {
    const file = fd.get("file"), paste = g("paste"), p = SP(me().id);
    const done = (text, name) => { if (text.trim().length < 80) { flash("warning", "That's too short to be a resume. Paste the whole thing."); return render(); }
      p.resume_text = text.slice(0, 20000); p.resume_name = name; if (!(p.skills || []).length) p.skills = N.extractSkills(text).slice(0, 20);
      const n = (p.items || []).length ? 0 : importResume(p);
      flash("verified", `Read ${name}.` + (n ? ` We also filled ${n} profile entr${n === 1 ? "y" : "ies"} from it; check them on your profile.` : "")); go("resume?tab=review"); };
    if (file && file.size) {
      const btn = f.querySelector("button[type=submit]"); if (btn) { btn.disabled = true; btn.textContent = "Reading…"; }
      readResumeFile(file).then(t => done(t, file.name.slice(0, 120)), msg => { flash("warning", String(msg)); render(); }); return; }
    if (paste) return done(cleanResumeText(paste), "Pasted text");
    flash("warning", "Choose a file or paste your resume."); return render();
  }
  if (id === "itemForm") {
    const p = SP(me().id), iid = Number(f.dataset.id) || 0, raw = {kind: f.dataset.kind, current: !!fd.get("current"), extra: {}};
    for (const k of ["title", "org", "location", "start", "end", "description", "url"]) raw[k] = String(fd.get(k) || "");
    for (const [k, v] of fd.entries()) if (k.startsWith("x_")) raw.extra[k.slice(2)] = String(v);
    let it; try { it = cleanItem(raw); } catch (err) { S.itemDraft = Object.assign({}, raw, {id: iid}); flash("warning", String(err)); return render(); }
    if (iid) { const cur = (p.items || []).find(x => x.id === iid); if (cur) Object.assign(cur, it); }
    else { try { addItem(p, it); } catch (err) { flash("warning", String(err)); return render(); } }
    S.itemDraft = null; return go("profile#" + it.kind);
  }
  if (f.classList.contains("stageForm")) { const c = S.candidates.find(x => x.job === S.route.q.id && x.student === Number(f.dataset.student) && x.employer === me().id);
    if (c && STAGE_NAME[g("stage")]) { c.stage = g("stage"); c.note = g("note").slice(0, 300); c.updated = NOW(); flash("verified", "Updated."); } return render(true); }
  if (id === "jobVersionForm") { S.versions.unshift({id: Date.now(), user: me().id, name: f.dataset.name || "Tailored copy", body: String(fd.get("body") || "").trim(), at: NOW()});
    flash("verified", "Saved a tailored copy. Your main resume didn't change."); return go("resume?tab=versions"); }
  if (id === "resumeSave") { const t = String(fd.get("text") || ""); if (t.trim().length < 80) { flash("warning", "A resume needs 80 to 20,000 characters."); return render(); }
    SP(me().id).resume_text = t.slice(0, 20000); flash("verified", "Saved."); return render(true); }
  if (id === "bulletForm") { S.bulletIn = g("bullet"); S.bulletOut = S.bulletIn ? N.improveBullet(S.bulletIn) : null; return render(true); }
  if (id === "tailorForm") {
    const p = SP(me().id), jid = Number(g("job_id")); let ttl, desc;
    if (jid) { const j = approvedJobs().find(x => x.id === jid); if (!j) return; ttl = j.title; desc = j.description; }
    else { ttl = g("title") || "this job"; desc = g("description"); if (desc.length < 60) { flash("warning", "Pick a listing, or paste a job description (at least a few sentences)."); return render(); } }
    S.tailor = {title: ttl, t: N.tailor(p.resume_text, ttl, desc, p)}; S.route.q.job = jid; return render();
  }
  if (id === "versionForm") { S.versions.unshift({id: Date.now(), user: me().id, name: g("name") || "Tailored copy", body: String(fd.get("body") || "").trim(), at: NOW()}); S.tailor = null; return go("resume?tab=versions"); }
});

reset();
render();
})();
