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
  mail: '<rect x="3.5" y="5.5" width="17" height="13" rx="1.5"/><path d="m4 7 8 6 8-6"/>',
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
   description: "Plan and schedule posts for our Instagram and LinkedIn, write short case-study captions, and track what performs in a weekly Excel sheet. Canva experience helps.\n\n10 to 12 hours a week during the semester. Paid internship at $16 per hour.", apply_url: "https://garnetanalytics.example/careers/social-intern",
   easy_apply: true, questions: [{q: "Why this role?", kind: "long", required: true}, {q: "Are you authorized to work in the US?", kind: "yesno", required: true}, {q: "Portfolio link", kind: "short", required: false}]},
  {id: 10, title: "Patient Services Assistant (Part-time)", company: "Bayside Dental", category: "Healthcare", work_type: "on-site", location: "Tallahassee, FL", state: "approved",
   description: "Check patients in, schedule visits, verify insurance and keep records up to date in our practice software. Spanish is a plus. 15 hours a week, weekday afternoons. $15 per hour.", apply_url: "https://baysidedental.example/jobs"},
];
const APPLY_FIX = {1: "https://garnetanalytics.example/careers", 2: "https://baysidedental.example/jobs", 3: "https://coastalpolicylab.example/ra",
  4: "https://panhandlefreight.example/work", 5: "https://brightpathstaffing.example/apply", 6: "https://quickcashstaffing.example/apply",
  7: "https://capitalrowpartners.example/internships"};
// Who posted each seeded employer listing (jobs.poster_name / poster_title / show_email on the site).
const POSTERS = {1: ["Pat Lee", "Campus Recruiter"], 2: ["Renee Owens", "Office Manager"], 3: ["Dr. Ana Ruiz", "Lab Director", 1], 6: ["Mike", "HR"],
  7: ["Chris Hall", "Talent Manager"], 9: ["Jamie Cole", "Marketing Lead"], 10: ["Renee Owens", "Office Manager"]};
const EMPLOYER_OF = {"Garnet Analytics": 4, "Bayside Dental": 5, "Coastal Policy Lab": 6, "QuickCash Staffing": 7, "Capital Row Partners": 8};

let S; // the whole demo state
function reset() {
  S = {users: [], students: {}, employers: {}, jobs: [], convos: [], posts: [], reports: [], inbox: [], tokens: {}, versions: [], dismissed: {}, suggs: {},
       session: null, admin: false, route: {name: "home", q: {}}, flash: null, draft: null, pendingDraft: null, nextId: 1, tokN: 0, mailN: 0, itemN: 0, applyClicks: new Set(), timers: [], candidates: [], views: {}, clicks: {}, schoolRequests: [], publicChecks: 0, apps: [], conns: [], follows: [], saves: [], savedJobs: [], connLog: [], easyDraft: null, chats: [], chatId: null};
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
    fsu_connection: "We hire three FSU interns every summer and table at the fall career fair.", tagline: "Campaign and survey dashboards for Florida nonprofits", founded: "2016",
    linkedin: "https://linkedin.com/company/garnet-analytics", hires_for: ["Data & Analytics", "Marketing"], perks: ["Paid", "Mentorship", "Return offers"], approved_at: t - 420 * 86400e3});
  emp("hr@baysidedental.example", {company: "Bayside Dental", website: "https://baysidedental.example", industry: "Healthcare", size: "11-50", location: "Tallahassee, FL",
    about: "A family dental practice with two offices in Tallahassee.", contact_name: "Renee Owens", contact_title: "Office Manager",
    fsu_connection: "Part-time front desk and patient services roles for FSU pre-health students.", tagline: "Family dentistry with two Tallahassee offices", founded: "2009",
    hires_for: ["Healthcare", "Admin & Office"], perks: ["Paid", "Flexible hours"], approved_at: t - 200 * 86400e3});
  emp("lab@coastalpolicylab.example", {company: "Coastal Policy Lab", website: "https://coastalpolicylab.example", industry: "Research", size: "1-10", location: "Remote",
    about: "A small research group studying coastal resilience policy in the Southeast.", contact_name: "Dr. Ana Ruiz", contact_title: "Lab Director",
    fsu_connection: "We hire FSU undergraduates as paid research assistants each semester.", tagline: "Coastal resilience policy research for the Southeast", founded: "2021",
    linkedin: "https://linkedin.com/company/coastal-policy-lab", hires_for: ["Research"], perks: ["Paid", "Remote-friendly", "Mentorship"], approved_at: t - 60 * 86400e3});
  emp("quickcash.hiring@gmail.com", {company: "QuickCash Staffing", website: "https://quickcashstaffing.example", industry: "Other", size: "1-10", location: "",
    about: "We connect remote workers with flexible payment processing roles across the country.", contact_name: "Mike", contact_title: "HR",
    fsu_connection: "We hire students.", status: "pending"});
  emp("recruiting@capitalrowpartners.example", {company: "Capital Row Partners", website: "https://capitalrowpartners.example", industry: "Finance & Banking", size: "51-200", location: "Tallahassee, FL",
    about: "A regional wealth management firm serving North Florida families and small businesses.", contact_name: "Chris Hall", contact_title: "Talent Manager",
    fsu_connection: "Our finance internship recruits from the FSU College of Business every spring.", status: "pending"});

  // Other students on the network (all visible, all taking connection requests), so "People you may know" has people in it.
  const sample = (name, major, grad, headline, skills, interests) => { const u = user(name.toLowerCase().replace(/[^a-z]/g, "") + "@fsu.edu", "student");
    S.students[u.id] = {display_name: name, major, degree: "Bachelor's", grad_term: grad, headline, skills, interests, work_types: ["hybrid"], job_kinds: ["internship"], links: {},
      resume_text: "", visible: true, share_resume: false, allow_messages: true, allow_connections: true, setup_step: 3, items: []}; return u; };
  const blair = sample("Blair N.", "Statistics", "Spring 2027", "Stats major who likes R and clean data", ["Python", "R", "SQL", "Excel"], ["Data & Analytics"]);
  const casey = sample("Casey D.", "Computer Science", "Spring 2027", "Building things with Python and JavaScript", ["Python", "JavaScript", "SQL", "Git"], ["Software & IT"]);
  const morgan = sample("Morgan T.", "Marketing", "Fall 2026", "Brand and social, looking for a summer internship", ["Social media", "Canva", "Content writing"], ["Marketing"]);
  const riley = sample("Riley S.", "Finance", "Spring 2028", "Finance student, Excel modeling and equity research club", ["Excel", "Financial modeling", "Communication"], ["Finance & Banking"]);
  sample("Sam K.", "Political Science", "Spring 2027", "Policy research and public speaking", ["Research", "Communication", "Spanish", "Excel"], ["Research"]);
  // Jordan's network: connected to Maya, one request waiting from Blair. Casey and Riley know Maya, so they show up with a mutual connection.
  const link = (x, y, by, status, note, at) => { const [a, b] = pair(x, y); S.conns.push({a, b, by, status, note: note || "", at, upd: at}); };
  link(j.id, m.id, m.id, "accepted", "", t - 20 * 86400e3);
  link(casey.id, m.id, casey.id, "accepted", "", t - 9 * 86400e3);
  link(riley.id, m.id, m.id, "accepted", "", t - 6 * 86400e3);
  link(blair.id, j.id, blair.id, "pending", "Hi Jordan, we're both in STA 4102. Would love to compare notes on the R project.", t - 5 * 3600e3);
  void morgan;

  const listings = NCS_SEED.concat(EXTRA_LISTINGS);
  S.jobs = listings.map((l, i) => {
    const pst = POSTERS[l.id] || ["", "", 0];
    const job = Object.assign({}, l, {apply_url: APPLY_FIX[l.id] || l.apply_url, employer_id: EMPLOYER_OF[l.company] || null, age_days: (listings.length - i) * 2,
      poster_name: pst[0], poster_title: pst[1], show_email: pst[2] ? 1 : 0});
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
  const r = N.scorePosting(j.title, j.description + ((j.questions || []).length ? "\n" + j.questions.map(q => q.q).join("\n") : ""), j.company, j.apply_url ? [j.apply_url] : null);
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
// Twins of ui.kpi, ui.hello_band, ui.fit_badge, ui.desk and ui.risk_meter (the site's Python), same markup.
const MEDIA = u => u === "arch-074.webp" ? NCS_FRAMES[74] : u === "arch-060.webp" ? NCS_FRAMES[60] : (NCS_MEDIA[u] || "");
const kpi = (n, l, go, hot) => go ? `<a class="kpi${hot ? " hot" : ""}" href="#" data-go="${go}"><span class="n">${n}</span><span class="l">${esc(l)}</span></a>` : `<div class="kpi${hot ? " hot" : ""}"><span class="n">${n}</span><span class="l">${esc(l)}</span></div>`;
const helloBand = (eyebrow, titleHtml, lede, kpis, photo) => `<section class="hello">${photo ? `<div class="ph" aria-hidden="true" style="--ph:url(${MEDIA(photo)})"></div>` : ""}<div class="eyebrow">${esc(eyebrow)}</div><h1>${titleHtml}</h1><p>${esc(lede)}</p>${kpis ? `<div class="kpis">${kpis}</div>` : ""}</section>`;
const fitBadge = (score, label) => `<span class="fitb${score >= 65 ? " hi" : score < 45 ? " lo" : ""}" style="--p:${score}" title="${esc(label || "Fit score")}"><i aria-hidden="true"></i><b>Fit ${score}</b></span>`;
// Twin of ui.risk_position / ui.risk_meter: 0-25 green, 26-50 yellow, 51-75 orange, 76-100 red; marker at the score.
const RISK_BANDS = [[0, 25], [26, 50], [51, 75], [76, 100]];
const RISK_MIN = 4, RISK_MAX = 96;   // never a perfect 0 or 100; an aggregator (score 0 by design) reads 60
const shownScore = (score, agg) => agg && score < 15 ? 60 : Math.max(RISK_MIN, Math.min(RISK_MAX, score));
function riskPosition(score, status, agg) {
  const sc = shownScore(score, agg), zone = RISK_BANDS.findIndex(([, hi]) => sc <= hi), [lo, hi] = RISK_BANDS[zone];
  return [zone, sc, Math.round((sc - lo) / (hi - lo) * 100) / 100];
}
const riskMeter = (score, status, agg) => { const [zone, pos] = riskPosition(score, status, agg);
  return `<div class="risk z${zone}" style="--pos:${pos}%"><span class="end">0</span><span class="gauge" role="img" aria-label="Scam risk ${pos} of 100">${[0, 1, 2, 3].map(i => `<i class="z${i}"></i>`).join("")}<b></b></span><span class="end">100</span><span class="rl">${pos}</span></div>`; };
const pageHead = (t, lede, num) => `<div class="page-head">${num ? `<div class="num">${esc(num)}</div>` : ""}<h1>${esc(t)}</h1>${lede ? `<p>${lede}</p>` : ""}</div>`;
const takeFlash = () => { const f = S.flash; S.flash = null; return f ? banner(f.kind, f.text, f.raw) : ""; };
const flash = (kind, text, raw) => { S.flash = {kind, text, raw}; };

// ---------------- quick apply + network helpers (twins of easyapply.py and network.py) ----------------
const MAX_QUESTIONS = 5, Q_LEN = 160, ANSWER_LEN = {short: 300, long: 1500, yesno: 3}, NOTE_LEN = 1000, DAILY_CAP = 40;
const Q_KINDS = [["short", "Short answer"], ["long", "Long answer"], ["yesno", "Yes / no"]];
// Things a real employer never needs to ask for on an application form (same list as easyapply._BANNED).
const BANNED_Q = /\b(ssn|social\s+security|routing\s+number|account\s+number|bank\s+(?:account|details|login)|credit\s+card|debit\s+card|card\s+number|cvv|password|passcode|passport|driver'?s?\s+licen[cs]e|gift\s+card|wire\s+transfer|cash\s?app|zelle|venmo|crypto)\b/i;
const CTRL = /[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/g;
function cleanQuestions(raw) {
  const out = [];
  for (const it of (raw || []).slice(0, MAX_QUESTIONS)) {
    const q = String(it.q || "").replace(CTRL, "").trim(); if (!q) continue;
    if (q.length > Q_LEN) throw `Keep each quick apply question under ${Q_LEN} characters.`;
    if (BANNED_Q.test(q)) throw "Quick apply questions can't ask for SSNs, bank or card details, passwords or ID numbers. Real employers collect those only after a hire, through their own paperwork.";
    out.push({q, kind: Q_KINDS.some(k => k[0] === it.kind) ? it.kind : "short", required: !!it.required});
  }
  return out;
}
const canApply = j => !!(j && j.easy_apply && j.review_status === "approved" && j.employer_id && approvedEmp(j.employer_id));
const myApp = (jid, uid) => S.apps.find(a => a.job === jid && a.student === uid);
function applicationHtml(a, p) {
  const rows = a.answers.map(x => `<div class="qa"><div class="q">${esc(x.q)}</div><div class="a">${x.a ? esc(x.a) : "<span class=faint>No answer</span>"}</div></div>`).join("");
  const note = a.note ? `<div class="qa"><div class="q">Note to you</div><div class="a">${esc(a.note)}</div></div>` : "";
  let resume = "";
  if (a.share && p.resume_text) resume = `<div class="qa"><div class="q">Resume</div><div class="a resume">${esc(p.resume_text)}</div></div>`;
  else if (!a.share) resume = '<p class="small faint" style="margin-top:6px">The student chose not to include a resume.</p>';
  const n = a.answers.length + (a.note ? 1 : 0), body = (rows + note + resume) || '<p class="small faint">No questions on this listing.</p>';
  return `<details class="appl"><summary><b>Application</b> <span class="faint">· sent ${ago(a.at)}${n ? ` · ${n} answer${n !== 1 ? "s" : ""}` : ""}</span></summary>${body}</details>`;
}

// Connections: one record per pair {a < b, by (who asked), status pending|accepted|declined, note}.
const PENDING_CAP = 50, NOTE_MAX = 200, SUGGEST_SHOW = 12;
const NET_TABS = [["connections", "Connections"], ["requests", "Requests"], ["discover", "People you may know"], ["following", "Following"]];
const NET_NOTES = {sent: ["verified", "Request sent."], accepted: ["verified", "You're connected."], declined: ["info", "Request declined."], removed: ["info", "Done."],
  followed: ["verified", "You're following that company."], unfollowed: ["info", "Unfollowed."],
  cap: ["warning", `You have ${PENDING_CAP} requests waiting. Let some get answered first.`],
  scam: ["warning", "That note looks like a scam signal, so it wasn't sent. Keep it to a sentence about who you are."],
  off: ["warning", "That student isn't taking connection requests."], limit: ["warning", "Too many requests just now. Try again later."]};
function pair(x, y) { return x < y ? [x, y] : [y, x]; }
const connRec = (x, y) => { const [a, b] = pair(x, y); return S.conns.find(c => c.a === a && c.b === b); };
function netState(who_, other) {   // none | sent | received | connected | declined (they turned my request down) | self
  if (who_ === other) return "self";
  const r = connRec(who_, other); if (!r) return "none";
  if (r.status === "accepted") return "connected";
  if (r.status === "declined") return r.by === who_ ? "declined" : "none";   // the decliner may still reach out themselves
  return r.by === who_ ? "sent" : "received";
}
const connIds = uid => S.conns.filter(c => c.status === "accepted" && (c.a === uid || c.b === uid)).map(c => c.a === uid ? c.b : c.a);
const mutualIds = (x, y) => { const ys = new Set(connIds(y)); return connIds(x).filter(i => ys.has(i)).sort((p, q) => p - q); };
const incomingReqs = uid => S.conns.filter(c => c.status === "pending" && c.by !== uid && (c.a === uid || c.b === uid)).sort((x, y) => y.at - x.at);
const canReceive = uid => { const u = U(uid), p = SP(uid); return !!(u && u.role === "student" && u.verified && studentReady(p) && p.allow_connections !== false); };
const isFollowing = (sid, eid) => S.follows.some(f => f.student === sid && f.employer === eid);
const followerCount = eid => S.follows.filter(f => f.employer === eid).length;
const followedIds = sid => S.follows.filter(f => f.student === sid).sort((x, y) => y.at - x.at).map(f => f.employer);
function suggestions(meId) {   // Students you may know: same major +3, same grad year +2, shared skills up to +3, mutual connections +2 each.
  const mine = SP(meId); if (!mine) return [];
  const known = new Set([meId]); S.conns.forEach(c => { if (c.a === meId || c.b === meId) { known.add(c.a); known.add(c.b); } });
  const myConn = new Set(connIds(meId)), mySkills = new Set((mine.skills || []).map(x => x.toLowerCase())), yr = t => (t || "").split(" ").pop(), scored = [];
  for (const uid of Object.keys(S.students).map(Number)) {
    const p = SP(uid), u = U(uid); if (known.has(uid) || !u || u.role !== "student" || !u.verified || !p.display_name || !p.major || p.allow_connections === false) continue;
    const why = []; let pts = 0;
    if (mine.major && p.major === mine.major) { why.push("Same major"); pts += 3; }
    if (mine.grad_term && p.grad_term && yr(p.grad_term) === yr(mine.grad_term)) { why.push("Class of " + yr(p.grad_term)); pts += 2; }
    const shared = (p.skills || []).filter(x => mySkills.has(x.toLowerCase()));
    if (shared.length) { why.push(`${shared.length} shared skill${shared.length !== 1 ? "s" : ""}`); pts += Math.min(3, shared.length); }
    const mutual = connIds(uid).filter(i => myConn.has(i)); if (mutual.length) { why.push(`${mutual.length} mutual`); pts += 2 * mutual.length; }
    scored.push({pts, uid, p, why});
  }
  scored.sort((x, y) => y.pts - x.pts || x.p.display_name.toLowerCase().localeCompare(y.p.display_name.toLowerCase()));
  const picked = scored.filter(x => x.pts > 0).slice(0, SUGGEST_SHOW).map(x => [x.uid, x.why]);
  if (picked.length < 6) { const seen = new Set(picked.map(x => x[0])); picked.push(...scored.filter(x => x.pts === 0 && !seen.has(x.uid)).slice(0, 6 - picked.length).map(x => [x.uid, ["New on the network"]])); }
  return picked;
}
function followButton(eid, following, next, small) {
  return `<button class="b${small === false ? "" : " sm"} ${following ? "sec" : "ghost"}" type="button" data-do="${following ? "unfollow" : "follow"}" data-id="${eid}" data-next="${esc(next || "")}"${following ? ' aria-pressed="true"' : ""}>${following ? "Following ✓" : "Follow"}</button>`;
}
function connectButton(other, st, next, noteField) {
  const at = `data-id="${other}" data-next="${esc(next || "")}"`;
  if (st === "connected") return `<span class="pill ok">✓ Connected</span><button class="b sm ghost" type="button" data-do="net-remove" ${at}>Remove</button>`;
  if (st === "sent") return `<span class="pill">Request sent</span><button class="b sm ghost" type="button" data-do="net-remove" ${at}>Withdraw</button>`;
  if (st === "received") return `<span class="row" style="gap:8px"><button class="b sm" type="button" data-do="net-accept" ${at}>Accept</button><button class="b sm ghost" type="button" data-do="net-decline" ${at}>Decline</button></span>`;
  if (st === "declined") return '<span class="pill">Not available</span>';
  return `<form class="navform cform2" data-to="${other}" data-next="${esc(next || "")}">${noteField ? `<input name="note" maxlength="${NOTE_MAX}" placeholder="Add a note (optional)" aria-label="Note" class="cnote">` : ""}<button class="b sm" type="submit">${icon("plus", 14)} Connect</button></form>`;
}
function connSection(uid, viewer, limit) {   // the Connections card on a student's profile (twin of network.connections_section)
  limit = limit || 8;
  const ids = connIds(uid).filter(i => (SP(i) || {}).display_name), own = uid === viewer, mutual = new Set(own ? [] : mutualIds(viewer, uid));
  let body;
  if (!ids.length) body = own ? '<p class="small muted" style="margin:0">No connections yet. <a href="#" data-go="network?tab=discover">Find classmates</a></p>' : '<p class="small muted" style="margin:0">No connections yet.</p>';
  else {
    ids.sort((x, y) => (mutual.has(x) ? 0 : 1) - (mutual.has(y) ? 0 : 1));
    const people = ids.slice(0, limit).map(i => { const [n, sub] = who(i);
      return `<a class="pconn" href="#" data-go="u?id=${i}"><span class="av" aria-hidden="true">${initials(n)}</span><span class="pc-t"><b>${esc(n)}</b><small>${esc(sub)}</small>${mutual.has(i) ? "<em>Mutual</em>" : ""}</span></a>`; }).join("");
    const more = own && ids.length > limit ? `<a class="small" href="#" data-go="network?tab=connections">See all ${ids.length}</a>` : "";
    body = `<div class="pconns">${people}</div>${more}`;
  }
  const head = plural(ids.length, "connection") + (mutual.size ? ` · ${mutual.size} mutual` : "");
  return `<section class="psec pconn-sec"><h3 class="sec">Connections <span class="faint">${esc(head)}</span></h3><div class="card">${body}</div></section>`;
}
function netStrip(viewer, other, next) {
  const n = connIds(other).length, mutual = mutualIds(viewer, other).length, st = netState(viewer, other);
  const btn = st !== "none" || canReceive(other) ? connectButton(other, st, next, true) : "";
  return `<div class="row netstrip">${btn}<span class="small faint">${plural(n, "connection")}${mutual ? ` · ${mutual} mutual` : ""}</span></div>`;
}
// Where an action lands: the network page shows every message; elsewhere only the warnings do (a state change is visible in the button itself).
function netBack(next, code) {
  next = next || "network";
  if (next.indexOf("network") === 0 || ["cap", "scam", "off", "limit"].includes(code)) flash(...NET_NOTES[code]);
  go(next);
}
function netConnect(to, note, next) {
  const meId = me().id, now = NOW();
  S.connLog = S.connLog.filter(x => now - x < 3600e3); if (S.connLog.length >= 60) return netBack(next, "limit"); S.connLog.push(now);
  note = String(note || "").replace(/\n/g, " ").replace(CTRL, "").trim().slice(0, NOTE_MAX);
  const st = netState(meId, to);
  if (st === "self" || (!canReceive(to) && st !== "received")) return netBack(next, "off");
  if (st === "received") { const r = connRec(meId, to); r.status = "accepted"; r.upd = now; return netBack(next, "accepted"); }   // they already asked me: connecting back is accepting
  if (st !== "none") return netBack(next, "removed");
  if (S.conns.filter(c => c.status === "pending" && c.by === meId).length >= PENDING_CAP) return netBack(next, "cap");
  if (note && ["block", "review"].includes(N.check(note).band)) return netBack(next, "scam");
  const [a, b] = pair(meId, to); S.conns = S.conns.filter(c => !(c.a === a && c.b === b));
  S.conns.push({a, b, by: meId, status: "pending", note, at: now, upd: now});
  return netBack(next, "sent");
}
function netRespond(other, action, next) {
  const r = connRec(me().id, other);
  if (netState(me().id, other) === "received" && (action === "accept" || action === "decline")) { r.status = action === "accept" ? "accepted" : "declined"; r.upd = NOW(); return netBack(next || "network?tab=requests", action === "accept" ? "accepted" : "declined"); }
  return netBack(next || "network?tab=requests", "removed");
}
function netRemove(other, next) {   // removes a connection, or withdraws a request you sent
  if (["connected", "sent"].includes(netState(me().id, other))) { const [a, b] = pair(me().id, other); S.conns = S.conns.filter(c => !(c.a === a && c.b === b)); }
  return netBack(next, "removed");
}

// The scam score only counts scam rules; a listing flagged by the separate aggregator check says so (same as app._score_pill).
function scorePill(j) {
  const lg = j.findings.some(f => f.rule_id === "lead_gen");
  return `Scam risk ${shownScore(j.score, lg)} · ${j.scam_status}`;
}

// ---------------- layout ----------------
const STUDENT_NAV = [["", [["home", "home", "Home"], ["jobs", "jobs", "Jobs"], ["spark", "assistant", "Career assistant"], ["feed", "feed", "Feed"], ["chat", "messages", "Messages"], ["mail", "emails", "Emails"], ["people", "network", "Network"]]],
  ["Career tools", [["send", "applications", "Applications"], ["file", "resume", "Resume studio"], ["shield", "scam", "Scam check"]]], ["You", [["user", "profile", "Profile"]]]];
const EMPLOYER_NAV = [["", [["home", "home", "Home"], ["jobs", "jobs", "Jobs"], ["feed", "feed", "Feed"], ["chat", "messages", "Messages"], ["mail", "emails", "Emails"], ["people", "talent", "Find students"]]],
  ["Hiring", [["jobs", "hiring", "Your listings"], ["plus", "post", "Post a job"], ["shield", "scam", "Scam check"]]], ["You", [["user", "profile", "Company profile"]]]];
function sidebar(active) {
  const n = unread(me().id), reqs = isStudent() ? incomingReqs(me().id).length : 0, mails = myEmails().filter(m => !m.read).length, out = [];
  for (const [grp, items] of (isStudent() ? STUDENT_NAV : EMPLOYER_NAV)) {
    if (grp) out.push(`<div class="grp">${esc(grp)}</div>`);
    for (const [ic, go, label] of items) out.push(`<a href="#" data-go="${go}"${go === active ? ' class="on" aria-current="page"' : ""}>${icon(ic)}<span>${esc(label)}</span>${go === "messages" && n ? `<span class="count" aria-label="${n} unread">${n}</span>` : go === "network" && reqs ? `<span class="count" aria-label="${reqs} connection requests">${reqs}</span>` : go === "emails" && mails ? `<span class="count" aria-label="${mails} unread emails">${mails}</span>` : ""}</a>`);
  }
  return `<aside class="side"><nav aria-label="Main">${out.join("")}</nav><div class="tip"><b>Stay safe:</b> real employers never ask you to pay, deposit a check, or buy gift cards. <a href="#" data-go="scam?kind=message">Check a message</a>.</div></aside>`;
}
function nav() {
  $("#inboxBtn").textContent = "Demo inbox" + (S.inbox.length ? ` (${S.inbox.length})` : "");
  const extra = S.admin ? '<a class="ghost" href="#" data-go="admin">Review queue</a>' : "";
  if (me()) $("#navActions").innerHTML = extra + `<span class="who">${esc(me().email)}</span><button class="ghostbtn" type="button" data-do="logout">Log out</button>` + (isEmployer() ? '<a class="btn" href="#" data-go="post">Post a job</a>' : "");
  else $("#navActions").innerHTML = extra + '<a class="ghost opt" href="#" data-go="scam">Scam check</a><a class="ghost" href="#" data-go="start">Log in</a><a class="btn" href="#" data-go="employers">For employers</a>';
}
const APP_PAGES = {hiring: "hiring", hjob: "hiring", home: "home", jobs: "jobs", job: "jobs", post: "post", posted: "post", assistant: "assistant", feed: "feed", messages: "messages", newmsg: "messages",
  resume: "resume", scam: "scam", profile: "profile", setup: "profile", item: "profile", talent: "talent", network: "network", applications: "applications", emails: "emails", easy: "jobs", u: "", company: "", about: "", privacy: "", report: ""};

// ---------------- pages ----------------
const P = {};
P.home = () => {
  if (me()) return me().role === "student" ? studentHome() : employerHome();
  const hero = NCS_BLOCKS.cineHero + NCS_BLOCKS.marquee + NCS_BLOCKS.nightCh + NCS_BLOCKS.scan + NCS_BLOCKS.howStudents + NCS_BLOCKS.fairCh;
  // Visitors see a teaser only: title, company, category. Listings are for signed-in FSU students and employers.
  const all = approvedJobs(), list = all.slice().reverse().slice(0, 3), emps = Object.values(S.employers).filter(p => p.status === "approved").length;
  const teaser = j => `<a class="job teaser" href="#" data-go="start?next=job-${j.id}"><div class="job-top"><div><div class="job-title">${esc(j.title)}</div><div class="job-co">${esc(j.company)}</div></div><span class="pill">${icon("shield", 13)} Log in to view</span></div><div class="job-meta"><span class="chip">${esc(j.category)}</span></div></a>`;
  return {wide: true, hero, body: `<section class="home-list"><h2 class="display section-title rv">Latest listings.</h2><p class="muted" style="margin:0 0 18px">${all.length} verified listing${all.length !== 1 ? "s" : ""} from ${emps} approved employer${emps !== 1 ? "s" : ""}, every one scam-checked and approved by a person. Log in with your @fsu.edu email to see the details and apply.</p><div class="teasers">${list.map(teaser).join("")}</div><p style="margin:16px 0 8px"><a href="#" data-go="start?next=jobs" style="color:var(--accent-ink);font-weight:600;text-decoration:none">Log in to see all jobs →</a></p></section>`};
};
function studentHome() {
  const p = SP(me().id); if (!p || !p.setup_step) { go("setup?step=1"); return null; }
  const h = new Date().getHours(), hello = h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
  const recs = N.rankJobs(approvedJobs(), p, "", 3), n = unread(me().id), [pct, missing] = completion(p);
  const recHtml = recs.map(r => `<a class="job" href="#" data-go="job?id=${r.job.id}" style="margin:0 0 8px"><div class="job-top"><div><div class="job-title" style="font-size:16px">${esc(r.job.title)}</div><div class="job-co">${esc(r.job.company)}</div></div>${r.fit ? fitBadge(r.fit.score, r.fit.label) : `<span class="pill accent">${r.score}% match</span>`}</div>${r.reasons.length ? `<div class="why">${esc(r.reasons[0])}</div>` : ""}</a>`).join("") || "<p>No listings yet.</p>";
  let resumeTile;
  if (p.resume_text) { const rv = N.review(p.resume_text);
    resumeTile = `<div class="tile w3"><h3>${icon("file")}Resume</h3><div class="score"><div class="ring" style="--p:${rv.score}"><b>${rv.score}</b></div><p>${esc(rv.grade)}. ${esc(rv.findings[0] ? rv.findings[0].message : "Looking good.")}</p></div><div class="foot"><a class="b sm sec" href="#" data-go="resume">Open resume studio</a></div></div>`; }
  else resumeTile = `<div class="tile w3"><h3>${icon("file")}Resume</h3><p>Add it for a score, line-by-line fixes, and a version tailored to any job.</p><div class="foot"><a class="b sm sec" href="#" data-go="resume">Add your resume</a></div></div>`;
  const posts = S.posts.filter(x => x.status === "published").sort((a, b) => b.at - a.at).slice(0, 2);
  const date = new Date().toLocaleDateString("en-US", {weekday: "long", month: "long", day: "numeric"});
  const first = (p.display_name || "").split(" ")[0], live = approvedJobs().length, best = Math.max(0, ...recs.map(r => r.fit ? r.fit.score : r.score));
  const kpis = kpi(live, `live listing${live !== 1 ? "s" : ""}, all reviewed`, "jobs") + (recs.length ? kpi(best, "your best fit right now", "jobs", best >= 65) : "") + kpi(n, `unread message${n !== 1 ? "s" : ""}`, "messages", n > 0);
  return `${helloBand(date, `${hello}${first ? "," : "."}${first ? `<br><em>${esc(first)}.</em>` : ""}`, "Here's what's new for you. Every listing and message is scanned for scams before you see it.", kpis, "arch-074.webp")}
<div class="bento"><div class="tile w4 tall"><h3>${icon("spark")}Recommended for you</h3>${recHtml}<div class="foot row"><a class="b sm" href="#" data-go="assistant">Ask the job assistant</a><a class="b sm sec" href="#" data-go="jobs">All jobs</a></div></div>
<div class="tile w2 goldt"><h3>${icon("chat")}Messages</h3><div class="big">${n}</div><p>unread message${n !== 1 ? "s" : ""}</p><div class="foot"><a class="b sm sec" href="#" data-go="messages">Open messages</a></div></div>
<div class="tile w2"><h3>${icon("shield")}Scam check</h3><p>Got a DM or email about a job? Paste it and get a verdict with the evidence.</p><div class="foot"><a class="b sm sec" href="#" data-go="scam?kind=message">Check a message</a></div></div>
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
  const live = mine.filter(j => j.review_status === "approved").length, st = mine.map(jobStats), viewed = st.reduce((a, x) => a + x.views, 0), cands = S.candidates.filter(c => mine.some(j => j.id === c.job)).length;
  const kpis = kpi(live, `live listing${live !== 1 ? "s" : ""}`, "hiring") + kpi(viewed, `student view${viewed !== 1 ? "s" : ""} of your listings`, "hiring") + kpi(cands, `candidate${cands !== 1 ? "s" : ""} in your tracker`, "hiring") + kpi(n, "unread", "messages", n > 0);
  return `${helloBand("Employer", `${hello},<br><em>${esc(p.company)}.</em>`, "Post roles for FSU students, answer messages, and share opportunities on the feed.", kpis, "office-960.webp")}
<div class="bento"><div class="tile w4 ${tile[0]}"><h3>${esc(tile[1])}</h3><p>${esc(tile[2])}</p><div class="foot">${tile[3]}</div></div>
<div class="tile w2"><h3>${icon("jobs")}Live listings</h3><div class="big">${mine.filter(j => j.review_status === "approved").length}</div><p>${mine.filter(j => j.review_status === "pending").length} waiting for review</p><div class="foot row"><a class="b sm" href="#" data-go="hiring">Matches &amp; stats</a><a class="b sm sec" href="#" data-go="post">Post a job</a></div></div>
<div class="tile w3"><h3>${icon("people")}Find students</h3><p>Search students who opted in, by skill or major.</p><div class="foot"><a class="b sm sec" href="#" data-go="talent">Open directory</a></div></div>
<div class="tile w3"><h3>${icon("feed")}FSU feed</h3><p>Share internships, info sessions and advice. Posts must be relevant to FSU students.</p><div class="foot"><a class="b sm sec" href="#" data-go="feed">Open the feed</a></div></div></div>`;
}
function completion(p) {
  const checks = [[!!p.display_name, "your name"], [!!p.major, "your major"], [!!p.grad_term, "your graduation term"], [(p.skills || []).length >= 3, "at least 3 skills"],
    [(p.interests || []).length > 0, "the kinds of jobs you want"], [!!p.resume_text, "a resume"], [!!p.headline, "a headline"],
    [(p.items || []).some(i => i.kind === "experience"), "an experience entry"], [(p.items || []).some(i => i.kind === "education"), "your education"],
    [(p.items || []).some(i => ["project", "certification", "organization"].includes(i.kind)), "a project, certification or organization"]];
  return [Math.round(100 * checks.filter(c => c[0]).length / checks.length), checks.filter(c => !c[0]).map(c => c[1])];
}

// ---------------- the job board (twin of jobboard.py): search + segmented tabs, filter rail, result cards, listing page ----------------
const JB_KINDS = [["full-time", "Full-time"], ["internship", "Internship"], ["part-time", "Part-time"]], JB_KIND_LABEL = {"full-time": "Full-time", internship: "Internship", "part-time": "Part-time", "on-campus": "On-campus"};
const JB_WHEN = [[0, "Any time"], [1, "Past 24 hours"], [7, "Past week"], [30, "Past month"]], JB_SORTS = [["relevant", "Most relevant"], ["recent", "Most recent"]];
const JB_LEVEL = {high: "High", medium: "Medium", low: "Low"}, JB_MAX_SAVED = 200, JB_MAX_LIST = 60;
const JB_CONF = {low: "Your profile is thin, so this is a rough estimate. Add experience, projects and a resume to sharpen it.", medium: "Based on part of your profile. Adding more sections makes it more accurate.",
  high: "Based on your whole profile: skills, resume, experience, projects, education and what you're looking for."};
const jbKinds = j => { const low = " " + (j.title + "\n" + j.description).toLowerCase() + " "; return Object.keys(N.KIND_WORDS).filter(k => N.KIND_WORDS[k].some(w => low.includes(w))); };
const jbWhere = j => j.location || (j.work_type === "remote" ? "Remote" : "");
const jbPosted = j => { const d = Math.floor(j.age_days || 0); return d < 1 ? "Posted today" : d < 2 ? "Posted yesterday" : d < 14 ? `Posted ${d} days ago` : `Posted ${Math.floor(d / 7)} weeks ago`; };
const jbLevel = pct => pct >= 75 ? "high" : pct >= 50 ? "medium" : "low";
const jbHasProfile = p => !!(p && ((p.skills || []).length || p.resume_text || (p.items || []).length));
const jbSaved = uid => S.savedJobs.filter(x => x.user === uid).sort((a, b) => b.at - a.at).map(x => x.job);
function jbParams(q, student) {
  const pick = (v, allowed, def) => allowed.includes((v || "").trim()) ? v.trim() : (def || "");
  return {search: (q.search || "").trim().slice(0, 200), category: pick(q.category, N.CATEGORIES), work_type: pick(q.work_type, N.WORK_TYPES), kind: pick(q.kind, JB_KINDS.map(k => k[0])),
    loc: (q.loc || "").trim().slice(0, 60), when: ["1", "7", "30"].includes(String(q.when)) ? Number(q.when) : 0, quick: String(q.quick) === "1" ? 1 : 0,
    following: student && String(q.following) === "1" ? 1 : 0, sort: pick(q.sort, JB_SORTS.map(s => s[0]), "relevant"), tab: student && q.tab === "saved" ? "saved" : "jobs"};
}
function jbUrl(p, over) {
  const cur = Object.assign({}, p, over || {}), qs = new URLSearchParams();
  for (const k of ["tab", "search", "category", "work_type", "kind", "loc", "when", "quick", "following", "sort"]) {
    const v = cur[k]; if (v === null || v === undefined || v === "" || v === 0 || (k === "tab" && v === "jobs") || (k === "sort" && v === "relevant")) continue; qs.set(k, v);
  }
  return "jobs" + (qs.toString() ? "?" + qs : "");
}
function jbFilter(jobs, p, followed) {
  return jobs.filter(j => (!p.category || j.category === p.category) && (!p.work_type || j.work_type === p.work_type) && (!p.kind || jbKinds(j).includes(p.kind))
    && (!p.when || (j.age_days || 0) <= p.when) && (!p.quick || j.easy_apply) && (!p.loc || (j.location || "").toLowerCase() === p.loc.toLowerCase()) && (!followed || followed.has(j.employer_id)));
}
function jbRank(jobs, p, profile) {
  const ranked = N.rankJobs(jobs, profile, p.search, 999), seen = new Set(ranked.map(r => r.job.id));
  if (p.search) { const t = p.search.toLowerCase(); jobs.forEach(j => { if (!seen.has(j.id) && ["title", "company", "description"].some(f => (j[f] || "").toLowerCase().includes(t))) ranked.push({job: j, score: 0}); }); }
  if (p.sort === "recent") ranked.sort((a, b) => (a.job.age_days || 0) - (b.job.age_days || 0));
  return ranked.map(r => ({job: r.job, fit: r.fit ? r.fit.score : null}));
}
const jbSaveBtn = (jid, saved, next, label) => { const t = saved ? "Remove from saved jobs" : "Save job";
  return `<span class="jc-sv"><button type="button" class="${label ? "sv-l" : "sv-i"}${saved ? " on" : ""}" data-do="${saved ? "job-unsave" : "job-save"}" data-id="${jid}" data-next="${esc(next)}" aria-label="${t}" title="${t}" aria-pressed="${saved}">${bookmark(saved, 18)}${label ? `<span>${saved ? "Saved" : "Save"}</span>` : ""}</button></span>`; };
// Card edge colour: the scam-check verdict plus the gauge zone (twin of jobboard.verdict_class).
function jbVerdict(j) {
  const zone = riskPosition(j.score, j.scam_status, j.findings.some(f => f.rule_id === "lead_gen"))[0];
  return `v-${["clear", "flagged", "held"].includes(j.scam_status) ? j.scam_status : "flagged"} z${zone}`;
}
function jbCard(j, p, fitpct, saved) {
  const match = fitpct !== null && fitpct !== undefined ? `<span class="jc-match ${jbLevel(fitpct)}">${fitpct}% match</span>` : "";
  const tags = `<span class="rev-score ${esc(j.scam_status)}">${esc(scorePill(j))}</span>` + match + (j.easy_apply ? '<span class="jc-tag q">Quick apply</span>' : "") + ((j.age_days || 0) < 7 ? '<span class="jc-tag n">New</span>' : "");
  const place = jbWhere(j), setting = cap(j.work_type);
  const facts = [place, place === setting ? "" : setting, jbKinds(j).slice(0, 2).map(k => JB_KIND_LABEL[k]).join(", ")].filter(Boolean).join(" · ");
  return `<article class="jc ${jbVerdict(j)}"><span class="jc-logo" aria-hidden="true">${initials(j.company)}</span><div class="jc-body"><h3 class="jc-title"><a class="jc-link" href="#" data-go="job?id=${j.id}">${esc(j.title)}</a></h3>`
    + `<div class="jc-co">${esc(j.company)} <span class="jc-cat">· ${esc(j.category)}</span></div><div class="jc-facts">${esc(facts)}</div><div class="jc-tags">${tags}</div></div>${saved === null ? "" : jbSaveBtn(j.id, saved, jbUrl(p))}</article>`;
}
const jbMenu = (label, items, active, cls) => `<details class="jb-dd ${cls || ""}"><summary class="jb-chip${active ? " on" : ""}">${esc(label)}<i class="car"></i></summary><div class="jb-menu">${items.map(([t, h, on]) => `<a href="#" data-go="${esc(h)}"${on ? " class=on aria-current=true" : ""}>${esc(t)}</a>`).join("")}</div></details>`;
const jbOpt = (label, href, on, kind) => `<a class="jb-opt ${kind || "check"}${on ? " on" : ""}" href="#" data-go="${esc(href)}"${on ? " aria-current=true" : ""}><i aria-hidden="true"></i><span>${esc(label)}</span></a>`;
const jbSec = (title, opts, open) => `<details class="jb-sec"${open ? " open" : ""}><summary>${esc(title)}<i class="car" aria-hidden="true"></i></summary><div class="jb-opts">${opts.join("")}</div></details>`;
const jbActive = p => ["category", "work_type", "kind", "loc", "when", "quick", "following"].filter(k => p[k]).length;
function jbRailSections(p, all, student) {
  const locs = {}; all.forEach(j => { if (j.location) locs[j.location] = (locs[j.location] || 0) + 1; });
  const top = Object.keys(locs).sort((a, b) => locs[b] - locs[a] || a.toLowerCase().localeCompare(b.toLowerCase())).slice(0, 8);
  const cats = [...new Set(all.map(j => j.category))].sort(), same = l => p.loc.toLowerCase() === l.toLowerCase();
  const more = [jbOpt("Quick apply", jbUrl(p, {quick: p.quick ? 0 : 1}), !!p.quick)];
  if (student) more.push(jbOpt("From companies I follow", jbUrl(p, {following: p.following ? 0 : 1}), !!p.following));
  return [
    jbSec("Job type", JB_KINDS.map(([k, label]) => jbOpt(label, jbUrl(p, {kind: p.kind === k ? null : k}), p.kind === k)), true),
    jbSec("Date posted", JB_WHEN.map(([d, t]) => jbOpt(t, jbUrl(p, {when: d}), p.when === d, "radio")), true),
    jbSec("Location", [jbOpt("Any location", jbUrl(p, {loc: null}), !p.loc, "radio")].concat(top.map(l => jbOpt(l, jbUrl(p, {loc: same(l) ? null : l}), same(l), "radio")),
      [jbOpt("Remote only", jbUrl(p, {work_type: p.work_type !== "remote" ? "remote" : null}), p.work_type === "remote")]), true),
    jbSec("Work setting", N.WORK_TYPES.map(w => jbOpt(cap(w), jbUrl(p, {work_type: p.work_type === w ? null : w}), p.work_type === w)), !!p.work_type),
    jbSec("Category", [jbOpt("All categories", jbUrl(p, {category: null}), !p.category, "radio")].concat(cats.map(c => jbOpt(c, jbUrl(p, {category: p.category === c ? null : c}), p.category === c, "radio"))), !!p.category),
    jbSec("More", more, true)].join("");
}
function jbRail(p, all, student) {   // twin of jobboard.rail: a sticky rail on wide screens, one "Filters" fold on narrow ones
  const n = jbActive(p), clear = n || p.search ? '<a class="jb-clear" href="#" data-go="jobs">Clear all</a>' : "", secs = jbRailSections(p, all, student), badge = n ? `<span class="jb-n">${n}</span>` : "";
  return `<aside class="jb-rail" aria-label="Filters"><div class="jb-rail-h"><h2>Filters${badge}</h2>${clear}</div>${secs}</aside>`
    + `<details class="jb-mf"><summary><span>Filters${badge}</span><i class="car" aria-hidden="true"></i></summary><div class="jb-mf-b">${secs}${clear ? `<div class="jb-mf-c">${clear}</div>` : ""}</div></details>`;
}
const jbSearchBox = p => `<form class="jb-search" id="jbSearch" role="search"><label class="sr" for="jb-q">Describe a job you want</label><input id="jb-q" name="search" value="${esc(p.search)}" placeholder="Describe a job you want" maxlength="200" autocomplete="off"><button type="submit">Search</button></form>`;
function jbTabs(p, student, nSaved) {
  if (!student) return "";
  const items = [["Jobs", "jobs", p.tab === "jobs"], [`Saved${nSaved ? ` (${nSaved})` : ""}`, "jobs?tab=saved", p.tab === "saved"], ["Resume optimizer", "resume", false]];
  return `<nav class="jb-seg" aria-label="Jobs">${items.map(([t, h, on]) => `<a href="#" data-go="${h}"${on ? " class=on aria-current=page" : ""}>${esc(t)}</a>`).join("")}</nav>`;
}
function jbBoard() {
  const student = isStudent(), p = jbParams(S.route.q, student), all = approvedJobs().slice().reverse();
  const prof = student ? SP(me().id) : null, rich = jbHasProfile(prof), saved = student ? jbSaved(me().id) : [];
  const followed = student && p.following ? new Set(followedIds(me().id)) : null;
  let ranked;
  if (p.tab === "saved") { const pool = saved.map(i => all.find(j => j.id === i)).filter(Boolean); const fm = rich ? Object.fromEntries(jbRank(pool, {search: "", sort: "relevant"}, prof).map(r => [r.job.id, r.fit])) : {}; ranked = pool.map(j => ({job: j, fit: rich ? (fm[j.id] === undefined ? null : fm[j.id]) : null})); }
  else ranked = jbRank(jbFilter(all, p, followed), p, rich ? prof : null);
  ranked = ranked.slice(0, JB_MAX_LIST);
  const savedSet = new Set(saved);
  const cards = ranked.map(r => jbCard(r.job, p, rich ? r.fit : null, student ? savedSet.has(r.job.id) : null)).join(""), n = ranked.length;
  let head, empty;
  if (p.tab === "saved") {
    head = `<div class="jb-count"><span>${plural(n, "saved job")}</span></div>`;
    empty = `<div class="empty">${bookmark(false, 36)}<p style="margin:10px 0 12px">No saved jobs yet. Tap the bookmark on any job to keep it here.</p><a class="b sec" href="#" data-go="jobs">Browse jobs</a></div>`;
  } else {
    const sort = jbMenu("Sort by " + JB_SORTS.find(s => s[0] === p.sort)[1], JB_SORTS.map(([s, t]) => [t, jbUrl(p, {sort: s}), p.sort === s]), false, "sort");
    head = `<div class="jb-count"><span>${plural(n, "job")}${p.search ? ` for “${esc(p.search)}”` : ""}</span>${sort}</div>`;
    empty = p.following ? '<div class="empty">Nothing from companies you follow right now. <a href="#" data-go="network?tab=following">Who you follow</a></div>' : '<div class="empty">No listings match. Try clearing filters or describing the job differently.</div>';
  }
  const side = p.tab === "jobs" ? jbRail(p, all, student) : "";
  return `<div class="jb"><div class="jb-top">${jbSearchBox(p)}${jbTabs(p, student, saved.length)}</div><div class="jb-grid${side ? "" : " solo"}">${side}<section class="jb-list" id="jb-list" aria-label="Results">${head}${cards || empty}</section></div></div>`;
}
function jbMarker(c, chosen) {
  const t = c.text.toLowerCase().replace(" (preferred)", "");
  for (const k of [t, t.split(":").slice(-1)[0].trim()]) if (k in chosen) return chosen[k] ? "Required" : "Preferred";
  for (const k of Object.keys(chosen)) if (new RegExp("(?<![a-z0-9])" + k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "s?(?![a-z0-9])").test(t)) return chosen[k] ? "Required" : "Preferred";
  return c.text.toLowerCase().includes("(preferred)") ? "Preferred" : "Required";
}
function jbQuals(job, f, personal) {
  const chosen = {}; N.qualsOf(job).forEach(q => { chosen[q.label.toLowerCase()] = !!q.must; });
  const items = (f || N.fitScore(job, {})).checklist;
  if (!items.length) return '<section class="jq"><h3>What they’re looking for</h3><p class="jq-sum muted">The employer hasn’t listed specific qualifications, and the description doesn’t name any.</p></section>';
  const marks = {met: ["✓", "met", "You have this"], missing: ["⊘", "missing", "Not on your profile yet"], unknown: ["?", "unknown", "Not enough on your profile to tell"]};
  const rows = items.map(c => { const [st, cls, tip] = personal ? marks[c.status] : ["•", "plain", ""], m = jbMarker(c, chosen);
    return `<li class="${cls}"><span class="mk" aria-hidden="true">${st}</span><div><span class="sr">${esc(tip)}: </span>${esc(c.text.replace(/\s*\(preferred\)$/, ""))}<em class="rq ${m.toLowerCase()}">${m}</em></div></li>`; }).join("");
  const met = items.filter(c => c.status === "met").length;
  const summ = personal ? `<p class="jq-sum"><b>You match ${met} of ${items.length} qualifications</b></p>` : `<p class="jq-sum muted">${plural(items.length, "qualification")} from the employer and the description.</p>`;
  const note = personal ? '<p class="jq-note">Matching is based on your profile. <a href="#" data-go="setup?step=1">Update profile</a></p>' : "";
  return `<section class="jq"><h3>What they’re looking for</h3>${summ}<ul class="jq-list">${rows}</ul>${note}</section>`;
}
function jbMatch(job, f) {
  if (!f) return '<section class="jm"><h3>Job match</h3><p class="muted small">Add your skills, experience or resume and every listing shows how well you match, built from your whole profile.</p><div class="row" style="margin-top:10px"><a class="b sm" href="#" data-go="profile">Build my profile</a><a class="b sm sec" href="#" data-go="resume">Add my resume</a></div></section>';
  const pct = f.percent, lvl = f.level;
  const parts = f.parts.map(x => `<div class="cat"><span>${esc(x.name)}</span><div class="meter${x.score >= 75 ? " ok" : x.score < 40 ? " warn" : ""}"><i style="width:${x.score}%"></i></div><span>${x.score}%</span><div class="why2">${esc(x.detail)}</div></div>`).join("");
  const found = f.matched.slice(0, 6).map(m => `<li><b>${esc(m.skill)}</b><span class="ev">Found in ${esc(m.where.slice(0, 2).map(w => w.replace(/^Your /, "your ")).join(", "))}</span></li>`).join("");
  const more = `<details class="jm-more"><summary class="jm-ai-b">${icon("spark", 15)}<span>Show match details</span></summary><div class="jm-more-b"><div class="fitparts">${parts}</div>${found ? `<h4 class="small" style="margin:12px 0 6px">Where your profile backs it up</h4><ul class="jm-found">${found}</ul>` : ""}</div></details>`;
  return `<section class="jm" id="fit"><div class="jm-head"><h3>Job match is <span class="jm-lvl ${lvl}">${JB_LEVEL[lvl]}</span></h3><span class="jm-pct">${pct}%</span></div>`
    + `<div class="jm-meter ${lvl}" style="--pos:${pct}%" role="img" aria-label="Job match ${pct} percent, ${JB_LEVEL[lvl].toLowerCase()}"><i></i><i></i><i></i><b></b></div><div class="jm-scale" aria-hidden="true"><span>Low</span><span>Medium</span><span>High</span></div><p class="jm-conf">${esc(JB_CONF[f.confidence])}</p>${jbAiActions(job, more)}</section>`;
}
// Twin of jobboard.ai_actions: match details, then the per-job tailoring pages (demo routes tailor / standout).
const jbAiActions = (job, more) => `<div class="jm-ai" role="group" aria-label="Help with this job">${more}`
  + [[`tailor?job=${job.id}`, "Tailor my resume"], [`standout?job=${job.id}`, "Help me stand out"], [`tailor?job=${job.id}&amp;mode=note`, "Draft a note to the poster"]]
    .map(([h, t]) => `<a class="jm-ai-b" href="#" data-go="${h}">${icon("spark", 15)}<span>${esc(t)}</span></a>`).join("") + "</div>";
function jbGlance(j) {
  const kinds = jbKinds(j).map(k => JB_KIND_LABEL[k]).join(", ") || "Not stated", how = j.easy_apply ? "Quick apply on NoleCareerShield" : (j.apply_url ? "Employer’s site" : "Contact the employer");
  const rows = [["Posted", cap(jbPosted(j).replace("Posted ", ""))], ["Job type", kinds], ["Work setting", cap(j.work_type)], ["Location", jbWhere(j) || "Not stated"], ["Category", j.category], ["How to apply", how]];
  return `<section class="jg"><h3>At a glance</h3><dl>${rows.map(([a, b]) => `<div><dt>${esc(a)}</dt><dd>${esc(b)}</dd></div>`).join("")}</dl></section>`;
}
function jbScam(j) {
  const ban = j.scam_status === "clear" ? banner("verified", "✓ This listing passed the scam check and was approved by a reviewer. Still verify the employer through their own website before sharing personal information.")
    : banner("warning", "⚠ This listing was approved but tripped some scam signals. Read the notes below and verify the employer independently before responding.");
  const fs = j.scam_status !== "clear" ? j.findings.filter(f => f.severity === "critical" || f.severity === "warning").map(f => `<div class="finding ${esc(f.severity)}"><b>${esc(f.title)}</b><br>${esc(f.why)}</div>`).join("") : "";
  return `<section class="js"><div class="js-top"><h3>Scam check</h3><span class="rev-score ${esc(j.scam_status)}">${esc(scorePill(j))}</span></div>${riskMeter(j.score, j.scam_status, j.findings.some(f => f.rule_id === "lead_gen"))}${ban}${fs ? `<div class="jd-find"><b style="font-size:14px">Signals to be aware of:</b>${fs}</div>` : ""}</section>`;
}
const QUICK_NOTE = '<p class="qa-note">Quick apply makes job applications short and sweet. However, experts recommend applying directly on company websites.</p>';
// Has this student applied: through Quick apply, or by opening the employer's own application link (twin of jobboard.applied).
const appliedTo = (jid, uid) => !!myApp(jid, uid) || S.applyClicks.has(jid + ":" + uid);
function posterBlock(j, empOk) {   // twin of jobboard.poster_block
  if (!j.employer_id) return "";
  const ep = EP(j.employer_id) || {};
  let name = (j.poster_name || ep.contact_name || "").trim();
  const title = (j.poster_title || ep.contact_title || "").trim();
  if (!name) name = "The hiring team";
  const u = j.show_email ? U(j.employer_id) : null;
  const email = u ? `<a class="jp-mail" href="mailto:${esc(u.email)}">${icon("mail", 14)} ${esc(u.email)}</a>` : "";
  const w = name.split(/\s+/), first = name === "The hiring team" ? "the hiring team"
    : esc(w.length > 1 && ["dr", "mr", "mrs", "ms", "mx", "prof", "professor"].includes(w[0].replace(/\.$/, "").toLowerCase()) ? `${w[0]} ${w[w.length - 1]}` : w[0]);
  let act = "";
  if (isStudent() && empOk) act = appliedTo(j.id, me().id) ? `<a class="b" href="#" data-go="newmsg?to=${j.employer_id}&amp;job=${j.id}">${icon("chat", 16)} Message ${first}</a>` : `<p class="jp-hint">You can message ${first} once you apply.</p>`;
  const whoTxt = esc(title + (title ? " at " : "") + j.company);
  return `<section class="jp"><h3>Meet the poster</h3><div class="jp-row"><span class="jc-logo" aria-hidden="true">${initials(name)}</span><div class="jp-who"><b>${esc(name)}</b><span>${whoTxt}</span>${email}</div>${act}</div></section>`;
}
function jbDetail(j, prof, next, record, saved, extra) {   // twin of jobboard.detail: the /job/ID page
  const student = isStudent(), empOk = !!j.employer_id && approvedEmp(j.employer_id);
  let co = esc(j.company), trust = "", apply = "", banr = "", following = false, done = null;
  if (empOk) { trust = trustPill(trustOf(j.employer_id), "company?id=" + j.employer_id + "#trust"); co = `<a href="#" data-go="company?id=${j.employer_id}">${co}</a>`; }
  if (student) {
    if (record) recordView(j.id, me().id);
    following = empOk && isFollowing(me().id, j.employer_id);
    done = j.easy_apply ? myApp(j.id, me().id) : null;
    if (j.easy_apply) {
      if (done) banr = `<div class="banner verified">✓ You applied ${ago(done.at)}. <a href="#" data-go="applications">Your applications</a></div>`;
      else if (empOk) { apply = `<a class="apply-btn" href="#" data-go="easy?id=${j.id}">Quick apply →</a>`;
        if (j.apply_url) apply += `<a class="b ghost" href="${esc(j.apply_url)}" data-apply="${j.id}" target="_blank" rel="noopener noreferrer nofollow ugc">Apply on company site</a>`; }
      else if (j.contact) banr = `<p style="font-size:14px;color:var(--muted)">Contact: ${esc(j.contact)}</p>`;
    } else if (j.apply_url) apply = `<a class="apply-btn" href="${esc(j.apply_url)}" data-apply="${j.id}" target="_blank" rel="noopener noreferrer nofollow ugc">Apply →</a>`;
    else if (j.contact) banr = `<p style="font-size:14px;color:var(--muted)">Contact: ${esc(j.contact)}</p>`;
  } else apply = `<a class="apply-btn" href="#" data-go="start?next=job-${j.id}">Log in as an FSU student to apply</a>`;
  let acts = apply;
  if (saved !== null) acts += jbSaveBtn(j.id, saved, next, true);
  if (student && empOk) acts += followButton(j.employer_id, following, "job?id=" + j.id, false);
  const own = isEmployer() && j.employer_id === me().id ? `<div class="banner info">This is your listing. <a href="#" data-go="hjob?id=${j.id}">See ranked student matches, candidates and stats →</a></div>` : "";
  const f = student && jbHasProfile(prof) ? N.fitScore(j, prof) : null;
  const sub = [jbWhere(j), jbWhere(j) === cap(j.work_type) ? "" : cap(j.work_type), jbPosted(j)].filter(Boolean).join(" · "), note = student && j.easy_apply && !done ? QUICK_NOTE : "";
  const top = `<div class="jd-top"><div class="jd-head"><span class="jc-logo lg" aria-hidden="true">${initials(j.company)}</span><div class="jd-h"><div class="jd-co">${co}</div><h1 class="jd-title">${esc(j.title)}</h1><div class="jd-sub">${esc(sub)}</div>${trust ? `<div class="jd-trust">${trust}</div>` : ""}</div></div>${own}<div class="jd-acts">${acts}</div>${note}${banr}</div>`;
  const side = `<aside class="jd-side" aria-label="Scam check and fit">${jbScam(j)}${student ? jbMatch(j, f) : ""}${jbQuals(j, f, !!f)}${posterBlock(j, empOk)}</aside>`;
  const body = `<div class="jd-body"><section class="jd-desc"><h2>About the job</h2><div class="detail-desc">${esc(j.description)}</div></section>${jbGlance(j)}${extra || ""}</div>`;
  return `<a class="back jd-back" href="#" data-go="jobs">← All jobs</a><article class="jd ${jbVerdict(j)}">${top}${side}${body}</article>`;
}
P.jobs = () => {
  if (!me()) { go("start?next=jobs"); return null; }
  if (S.route.q.job) { go("job?id=" + S.route.q.job); return null; }   // the old two-pane address opens the listing page
  return jbBoard();
};
P.job = () => {
  if (!me()) { go("start?next=job-" + S.route.q.id); return null; }
  const j = S.jobs.find(x => x.id === S.route.q.id);
  if (!j || j.review_status !== "approved") return '<p class="empty" style="margin:40px 0">That listing isn\'t available.</p>';
  const student = isStudent(), p = student ? SP(me().id) : null;
  return `<div class="jb jb-page">${jbDetail(j, p, "job?id=" + j.id, true, student ? jbSaved(me().id).includes(j.id) : null, student ? tailorPanel(j, p) : "")}</div>`;
};
P.post = () => {
  const v = S.draft || {}, val = n => esc(v[n] || "");
  const qv = Array.isArray(v.questions) ? v.questions.slice() : []; while (qv.length < MAX_QUESTIONS) qv.push({});
  const qRows = qv.slice(0, MAX_QUESTIONS).map((q, i) => `<div class="qrow"><label class="sr" for="f-qtext${i}">Question ${i + 1}</label><input id="f-qtext${i}" name="qtext" maxlength="${Q_LEN}" placeholder="Question ${i + 1}" value="${esc(q.q || "")}">`
    + `<label class="sr" for="f-qkind${i}">Answer type for question ${i + 1}</label><select id="f-qkind${i}" name="qkind">${Q_KINDS.map(([k, n]) => `<option value="${k}"${q.kind === k ? " selected" : ""}>${esc(n)}</option>`).join("")}</select>`
    + `<label class="sr" for="f-qreq${i}">Required or optional for question ${i + 1}</label><select id="f-qreq${i}" name="qreq"><option value="0">Optional</option><option value="1"${q.required ? " selected" : ""}>Required</option></select></div>`).join("");
  return `${pageHead("Submit a job", "Submitting isn't publishing. Every listing is scam-scanned and then reviewed by a person before it appears.", me() ? "Hiring" : "")}${takeFlash()}
<form id="postForm" class="card" style="max-width:720px">
<div class="form-field"><label for="f-title">Job title</label><input id="f-title" name="title" required maxlength="200" placeholder="e.g. Marketing Data Analyst" value="${val("title")}"></div>
<div class="form-field"><label for="f-company">Company</label><input id="f-company" name="company" required maxlength="200" placeholder="e.g. Leaf Home" value="${val("company") || (isEmployer() ? esc(EP(me().id).company || "") : "")}"></div>
<div class="grid2"><div class="form-field"><label for="f-category">Category</label><select id="f-category" name="category">${N.CATEGORIES.map(c => `<option${v.category === c ? " selected" : ""}>${esc(c)}</option>`).join("")}</select></div>
<div class="form-field"><label for="f-work_type">Work type</label><select id="f-work_type" name="work_type">${N.WORK_TYPES.map(w => `<option value="${w}"${v.work_type === w ? " selected" : ""}>${cap(w)}</option>`).join("")}</select></div></div>
<div class="form-field"><label for="f-location">Location</label><p class="hint">City/state, or leave blank if fully remote.</p><input id="f-location" name="location" maxlength="120" placeholder="e.g. Tallahassee, FL" value="${val("location")}"></div>
<div class="form-field"><label for="f-description">Description</label><p class="hint">The full posting: responsibilities, requirements, and pay if you can share it.</p><textarea id="f-description" name="description" required maxlength="8000">${val("description")}</textarea></div>
<div class="form-field"><label for="f-apply_url">Apply URL</label><p class="hint">Where applicants should go. The scanner checks this link too.</p><input id="f-apply_url" name="apply_url" maxlength="2000" placeholder="https://..." value="${val("apply_url")}"></div>
<fieldset class="form-field easyset"><legend>Who's posting</legend>
<p class="hint">Your name appears on the listing so students know who they'd be talking to. Students who apply can message you on NoleCareerShield.</p>
<div class="form-field"><label for="f-poster_name">Your name</label><input id="f-poster_name" name="poster_name" maxlength="80" placeholder="e.g. Dana Whitfield" value="${val("poster_name")}"></div>
<div class="form-field"><label for="f-poster_title">Your job title</label><input id="f-poster_title" name="poster_title" maxlength="80" placeholder="e.g. Campus Recruiting Manager" value="${val("poster_title")}"></div>
<label class="toggle" for="f-show_email"><input id="f-show_email" type="checkbox" name="show_email" value="1"${v.show_email ? " checked" : ""}><span><b>Show my email on this listing.</b> Off by default. Students can always message you here after they apply.</span></label>
<label class="toggle" for="f-direct" style="margin-top:12px"><input id="f-direct" type="checkbox" name="direct" value="1" required${v.direct ? " checked" : ""}><span><b>I work directly for this company.</b> Staffing agencies and second- or third-party recruiters can't post jobs for a client.</span></label></fieldset>
<fieldset class="form-field easyset"><legend>Quick apply</legend>
<label class="toggle" for="f-easy"><input id="f-easy" type="checkbox" name="easy_apply" value="1"${v.easy_apply ? " checked" : ""}><span><b>Collect applications on NoleCareerShield.</b> Students apply from their profile in one step, and you get their answers in your candidate tracker. Leave it off to send them to your Apply URL.</span></label>
<p class="hint" style="margin-top:10px">Optional questions for applicants (up to ${MAX_QUESTIONS}). Nothing that asks for an SSN, bank or card details or a password.</p>${qRows}</fieldset>
<button class="submit-btn" type="submit">Submit for review</button><p class="fine" style="text-align:left">${isEmployer() ? "Sending as " + esc(me().email) + "." : "You'll log in or sign up before it sends."}</p></form>`;
};
P.posted = () => `${pageHead("Submitted for review")}${banner("info", "Thanks, your listing was scanned and is now waiting for a person to approve it. Nothing is published automatically. Open the reviewer view to see its score and approve it, and check the demo inbox for the receipt.")}<div class="row"><a class="b" href="#" data-go="admin">Open the reviewer view</a><a class="b sec" href="#" data-go="home">Home</a></div>`;

// ---- quick apply (twin of easyapply.py) ----
function easyField(i, q, value) {
  const req = q.required ? " required" : "", label = `${esc(q.q)}${q.required ? "" : " <span class=faint>(optional)</span>"}`, fid = "a" + i;
  if (q.kind === "yesno") return `<fieldset class="form-field"><legend>${label}</legend><div class="row">${["Yes", "No"].map(v => `<label class="pick"><input type="radio" name="${fid}" value="${v}"${req}${value === v ? " checked" : ""}> ${v}</label>`).join("")}</div></fieldset>`;
  if (q.kind === "long") return `<div class="form-field"><label for="${fid}">${label}</label><textarea id="${fid}" name="${fid}" maxlength="${ANSWER_LEN.long}"${req}>${esc(value)}</textarea></div>`;
  return `<div class="form-field"><label for="${fid}">${label}</label><input id="${fid}" name="${fid}" maxlength="${ANSWER_LEN.short}"${req} value="${esc(value)}"></div>`;
}
P.easy = () => {
  if (!isStudent()) return needStudent("quick apply");
  const j = S.jobs.find(x => x.id === S.route.q.id), unavailable = msg => pageHead("Quick apply") + `<div class="empty">${esc(msg)} <a href="#" data-go="jobs">Back to jobs</a></div>`;
  if (!j || !canApply(j)) return unavailable("That listing isn't taking applications here.");
  const p = SP(me().id); if (!studentReady(p)) { go("setup?step=1"); return null; }
  if (myApp(j.id, me().id)) { flash("info", "You already applied to that listing."); go("applications"); return null; }
  const dr = S.easyDraft, v = dr ? dr.typed : {}, qs = j.questions || [];
  const fields = qs.map((q, i) => easyField(i, q, v["a" + i] || "")).join("");
  const sub = [p.major, p.grad_term && "Graduating " + p.grad_term].filter(Boolean).join(" · ");
  const resume = p.resume_text ? `<label class="toggle"><input type="checkbox" name="share_resume" value="1"${!dr || v.share_resume === "1" ? " checked" : ""}><span><b>Include my resume.</b> The employer sees the resume saved on your profile.</span></label>`
    : '<p class="small faint">You haven\'t added a resume yet, so none will be sent. <a href="#" data-go="resume">Resume studio</a></p>';
  return `<a class="back" href="#" data-go="job?id=${j.id}">← ${esc(j.title)}</a>` + pageHead("Quick apply", `${esc(j.title)} at ${esc(j.company)}. Your profile fills in the basics; answer the questions and send.`, "Apply")
    + QUICK_NOTE + (dr && dr.error ? banner("warning", dr.error) : "")
    + `<form id="easyForm" data-job="${j.id}" class="card easy"><div class="row" style="gap:12px;align-items:center;margin-bottom:14px"><div class="person"><span class="avatar">${initials(p.display_name)}</span><div style="min-width:0"><div class="nm">${esc(p.display_name)}</div><div class="sub">${esc(sub)}</div></div></div></div>`
    + fields
    + `<div class="form-field"><label for="a-note">Note to the employer <span class="faint">(optional)</span></label><textarea id="a-note" name="note" maxlength="${NOTE_LEN}" placeholder="Anything you want them to know">${esc(v.note || "")}</textarea></div>`
    + resume
    + `<p class="small muted" style="margin:14px 0">The employer will see your name, major, graduation term, profile links, these answers and the resume if ticked. Nothing else from your account, and never your email. You can withdraw the application any time.</p>`
    + `<button class="b" type="submit">${icon("send", 16)} Send application</button> <a class="b ghost" href="#" data-go="job?id=${j.id}">Cancel</a></form>`;
};
function sendApplication(f, fd) {
  const j = S.jobs.find(x => x.id === Number(f.dataset.job)), p = SP(me().id);
  if (!canApply(j)) return go("jobs");
  if (myApp(j.id, me().id)) { flash("info", "You already applied to that listing."); return go("applications"); }
  const qs = j.questions || [], typed = {};
  qs.forEach((q, i) => { typed["a" + i] = String(fd.get("a" + i) || ""); });
  typed.note = String(fd.get("note") || ""); typed.share_resume = fd.get("share_resume") ? "1" : "0";
  const clean = t => t.replace(/\r\n/g, "\n").replace(CTRL, "").trim(), answers = []; let error = "";
  qs.forEach((q, i) => {
    let a = clean(typed["a" + i]); if (q.kind === "yesno" && !["", "Yes", "No"].includes(a)) a = "";
    if (q.required && !a) error = "Answer the required questions first. Your other answers are still here.";
    if (a.length > ANSWER_LEN[q.kind]) error = `One answer is too long (up to ${ANSWER_LEN[q.kind].toLocaleString("en-US")} characters).`;
    answers.push({q: q.q, a});
  });
  const note = clean(typed.note); if (note.length > NOTE_LEN) error = `The note can be up to ${NOTE_LEN.toLocaleString("en-US")} characters.`;
  if (!error && S.apps.filter(a => a.student === me().id && NOW() - a.at < 86400e3).length >= DAILY_CAP) error = "That's a lot of applications for one day. Try again tomorrow.";
  if (error) { S.easyDraft = {typed, error}; return render(true); }
  S.apps.push({job: j.id, student: me().id, employer: j.employer_id, answers, note, share: typed.share_resume === "1" && !!p.resume_text, at: NOW()});
  addCandidate(j.id, me().id, j.employer_id, "applied");
  (S.clicks[j.id] = S.clicks[j.id] || new Set()).add(me().id); recordView(j.id, me().id);
  flash("verified", "Application sent. The employer sees it in their candidate tracker.");
  go("applications");
}
P.applications = () => {
  if (!isStudent()) return needStudent("applications");
  const head = pageHead("Your applications", "Everything you sent with quick apply. Employers see it only while it's here.", "Apply") + takeFlash();
  const apps = S.apps.filter(a => a.student === me().id).sort((x, y) => y.at - x.at);
  if (!apps.length) return head + '<div class="empty">No applications yet. Listings with a <b>Quick apply</b> button let you apply without leaving the site. <a href="#" data-go="jobs">Browse jobs</a></div>';
  return head + apps.map(a => { const j = S.jobs.find(x => x.id === a.job) || {title: "Listing", company: ""};
    return `<div class="card app"><div class="row between" style="align-items:flex-start;gap:12px"><div style="min-width:0"><a class="job-title" href="#" data-go="job?id=${a.job}">${esc(j.title)}</a><div class="job-co">${esc(j.company)} · sent ${ago(a.at)}</div></div><button class="b sm ghost" type="button" data-do="withdraw" data-id="${a.job}">Withdraw</button></div></div>`; }).join("");
};

// ---- network (twin of network.py) ----
P.network = () => {
  if (!isStudent()) return needStudent("the network");
  const meId = me().id, incoming = incomingReqs(meId), outgoing = S.conns.filter(c => c.status === "pending" && c.by === meId).sort((x, y) => y.at - x.at);
  const conns = connIds(meId), follows = followedIds(meId), counts = {connections: conns.length, requests: incoming.length, following: follows.length};
  const tab = NET_TABS.some(t => t[0] === S.route.q.tab) ? S.route.q.tab : (incoming.length ? "requests" : "connections");
  const card = (uid, extra, why) => `<div class="card ncard"><div class="row between" style="align-items:center;gap:12px"><div style="min-width:0">${person(uid)}${why && why.length ? `<div class="chips" style="margin-top:8px">${why.map(w => `<span class="chip">${esc(w)}</span>`).join("")}</div>` : ""}</div><div class="row">${extra}</div></div></div>`;
  const head = pageHead("Your network", "Students you're connected with and companies you follow. Nobody here can message you: connecting is how you see each other on the network.", "Network");
  let body;
  if (tab === "connections") body = conns.sort((x, y) => who(x)[0].toLowerCase().localeCompare(who(y)[0].toLowerCase())).map(uid => card(uid, connectButton(uid, "connected", "network"))).join("")
    || '<div class="empty">No connections yet. <a href="#" data-go="network?tab=discover">See people you may know</a>, or open a classmate\'s profile from the Feed.</div>';
  else if (tab === "requests") {
    const inc = incoming.map(r => card(r.by, connectButton(r.by, "received", "network?tab=requests")) + (r.note ? `<p class="small muted rnote">“${esc(r.note)}”</p>` : "")).join("");
    const out = outgoing.map(r => { const o = r.a === meId ? r.b : r.a; return card(o, connectButton(o, "sent", "network?tab=requests")); }).join("");
    body = (inc ? `<h3 class="sec">Waiting for you</h3>${inc}` : '<div class="empty">No requests waiting for you.</div>') + (out ? `<h3 class="sec">You sent</h3>${out}` : "");
  } else if (tab === "discover") {
    body = '<p class="small muted" style="margin-bottom:12px">Ranked by shared major, graduation year, skills and mutual connections. Students can switch this off in their profile.</p>'
      + (suggestions(meId).map(([uid, why]) => card(uid, connectButton(uid, "none", "network?tab=discover", false), why)).join("")
        || '<div class="empty">Nobody new to suggest yet. As more students set up their profiles, people from your major and class show up here.</div>');
  } else {
    body = follows.filter(approvedEmp).map(eid => { const p = EP(eid), n = approvedJobs().filter(j => j.employer_id === eid).length;
      return `<div class="card ncard"><div class="row between" style="align-items:center;gap:12px"><div style="min-width:0"><div class="person"><span class="avatar emp">${initials(p.company)}</span><div style="min-width:0"><div class="nm"><a href="#" data-go="company?id=${eid}" style="text-decoration:none">${esc(p.company)}</a></div><div class="sub">${esc(p.industry || "Approved employer")}</div></div></div><p class="small muted" style="margin-top:6px">${plural(n, "open listing")}</p></div><div class="row">${followButton(eid, true, "network?tab=following")}</div></div></div>`; }).join("")
      || '<div class="empty">You aren\'t following any companies yet. Open a company profile or a listing and press Follow to get their new jobs in one filter.</div>';
  }
  const tabs = '<div class="seg" role="tablist" style="margin:18px 0">' + NET_TABS.map(([k, v]) => `<a href="#" data-go="network?tab=${k}"${k === tab ? ' class="on" aria-current="page"' : ""}>${esc(v)}${counts[k] ? ` <span class="faint">(${counts[k]})</span>` : ""}</a>`).join("") + "</div>";
  return head + takeFlash() + tabs + body;
};

// ---- scam check ----
// The full evidence is for FSU students and approved employers (same as msgcheck.full_view): enough to spot a scam, not to tune one.
const fullView = () => !!me() && (isStudent() || approvedEmp(me().id));
function publicVerdictHtml(r) {
  const shown = (r.findings.filter(f => f.severity !== "note").length ? r.findings.filter(f => f.severity !== "note") : r.findings).slice(0, 3), more = r.findings.length - shown.length;
  const items = shown.map(f => `<li><b>${esc(f.title)}</b><span class="ev">${esc(f.why)}</span></li>`).join("") || '<li><b>No scam patterns matched.</b><span class="ev">The detector checked for more than 30 known student-scam patterns.</span></li>';
  return `<section class="verdict ${r.key}" aria-live="polite"><div class="eyebrow" style="color:inherit">Verdict</div><h2>${icon("shield", 22)}${esc(r.title)}</h2><p>${esc(r.advice)}</p><ul class="reasons">${items}</ul></section>
<div class="banner info" style="margin-top:12px">FSU students see ${more > 0 ? `${more} more signal${more !== 1 ? "s" : ""}, ` : ""}the exact words each signal caught and the link and sender checks, and can check messages straight from their inbox. <a href="#" data-go="start">Log in with your @fsu.edu email</a></div>
<h3 class="sec">What to do next</h3><ol class="next">${(r.steps || N.NEXT_STEPS[r.level]).map(s => `<li>${esc(s)}</li>`).join("")}</ol>`;
}
function schoolForm() {
  if (me()) return "";
  if (S.schoolDone) { const d = S.schoolDone; S.schoolDone = ""; return `<div class="card" style="margin-top:22px"><b>Thanks.</b> <span class="muted">We'll count ${esc(d)}.</span></div>`; }
  return `<form id="schoolForm" class="card" style="margin-top:22px"><b>Want NoleCareerShield at your school?</b><p class="small muted" style="margin:4px 0 10px">Tell us which one. We only keep the school name, nothing about you.</p>
<div class="row" style="flex-wrap:nowrap"><label for="c-school" class="hp">Your school</label><input id="c-school" name="school" maxlength="80" required placeholder="e.g. University of Florida" style="flex:1;min-width:0"><button class="b sm" type="submit">Send</button></div></form>`;
}
function verdictHtml(r, from) {
  const items = r.findings.slice(0, 8).map(f => `<li><b>${esc(f.title)}</b> <span class="pill ${f.severity === "critical" ? "bad" : f.severity === "warning" ? "warn" : ""}">${{critical: "strong signal", warning: "warning", note: "note"}[f.severity]}</span><span class="ev">${esc(f.why)}</span>${f.matched && f.matched.length ? `<span class="ev">Found: “${esc(f.matched.join("”, “"))}”</span>` : ""}</li>`).join("")
    + (r.lead_gen.flag ? `<li><b>Looks like a data-harvesting or aggregator ad</b><span class="ev">${esc(r.lead_gen.verdict)}</span></li>` : "")
    || '<li><b>No scam patterns matched.</b><span class="ev">The detector checked for more than 30 known student-scam patterns, the sender and every link.</span></li>';
  const plat = from ? `<p class="small" style="margin-top:8px">Sent through NoleCareerShield by <b>${esc(who(from)[0])}</b>, ${approvedEmp(from) ? "an employer our reviewers approved" : "an employer our reviewers have not approved"}.</p>` : "";
  return `<section class="verdict ${r.key}" aria-live="polite"><div class="eyebrow" style="color:inherit">Verdict</div><h2>${icon("shield", 22)}${esc(r.title)}</h2><p>${esc(r.advice)}</p>${plat}<ul class="reasons">${items}</ul></section>
<h3 class="sec">What to do next</h3><ol class="next">${(r.steps || N.NEXT_STEPS[r.level]).map(s => `<li>${esc(s)}</li>`).join("")}</ol>`;
}

// ---- checking a job listing found elsewhere (same as msgcheck.check_listing) ----
const LISTING_LEVELS = [
  ["ok", "No known scam signs", "Nothing in this listing matches a known scam pattern. That isn't a guarantee: find the same job on the employer's own careers page before you apply."],
  ["caution", "Be careful", "A few things in this listing are off. Confirm it on the employer's own website before you apply or share anything."],
  ["warn", "Likely a scam", "Several strong scam signals. Don't apply through this listing and don't send personal or bank details."],
  ["bad", "Scam. Stop here.", "This listing matches patterns that only scams use. Don't apply, reply or send anything."]];
const LISTING_STEPS = {
  0: ["Find the same job on the employer's own careers page and apply there.", "Never pay for training, equipment or a background check. Real jobs don't charge you.", "Don't give your SSN or bank details until you have a real offer."],
  1: ["Look for the same listing on the company's own website before you apply.", 'Search the company name with the word "scam" and read what others found.', "Don't put your SSN, bank details or a photo of your ID in an application."],
  2: ["Don't apply through this listing or its link.", "Look the company up yourself. If the job isn't on their own site, skip it.", "If you found it on Handshake, LinkedIn or Indeed, report the listing there."],
  3: ["Don't apply, reply or send anything.", "If you already sent money or bank details, or deposited a check they sent, call your bank now.", "Report the listing where you found it, and report fraud at reportfraud.ftc.gov."]};
const LEADGEN_STEP = "This looks like an aggregator or lead-generation ad. Find the employer's own posting and apply there instead of giving this site your details.";
function checkListing(v) {
  const res = N.scorePosting(v.title, v.description + (v.contact ? "\n" + v.contact : ""), v.company, v.url ? [v.url] : null);
  const have = new Set(res.findings.map(f => f.rule_id)), extra = N.linkFindings(v.description + " " + v.url).filter(f => !have.has(f.rule_id));
  const findings = res.findings.concat(extra).sort((a, b) => ({critical: 0, warning: 1, note: 2}[a.severity] - {critical: 0, warning: 1, note: 2}[b.severity]) || b.weight - a.weight);
  const score = Math.min(100, res.score + extra.reduce((n, f) => n + f.weight, 0)), critical = findings.some(f => f.severity === "critical");
  const band = critical || score >= 65 ? "block" : score >= 35 ? "review" : score >= 15 ? "caution" : "clear";
  let level = {clear: 0, caution: 1, review: 2, block: 3}[band]; if (res.lead_gen.flag && level < 1) level = 1;
  const [key, title, advice] = LISTING_LEVELS[level];
  return {kind: "listing", level, key, title, advice, score, band, findings, lead_gen: res.lead_gen, steps: (res.lead_gen.flag ? [LEADGEN_STEP] : []).concat(LISTING_STEPS[level])};
}
const LISTING_SAMPLES = [
  ["Check-cashing gig", {title: "Remote Admin Assistant", company: "QuickCash Staffing", description: "Part-time remote assistant, $500 weekly, no experience needed. We will send you a check to buy office equipment from our vendor. Deposit it and send the rest by Zelle.", url: "", contact: "quickcash.hiring@gmail.com"}],
  ["Aggregator ad", {title: "Sales Lead Specialist", company: "JobMatch Network", description: "Create a free profile to see the employer and apply to hundreds of similar openings. Sign up to unlock full job details. Our partners will contact you about matching roles.", url: "https://example.com/jobmatch/signup?ref=track123&utm_source=feed", contact: ""}],
  ["Real internship", {title: "Data Analyst Intern", company: "Garnet Analytics", description: "Summer internship building SQL dashboards for city clients. $18/hour, 20 hours a week, hybrid in Tallahassee. Apply on our careers page.", url: "https://garnetanalytics.example/careers", contact: ""}]];
function listingForm(v) {
  v = v || {}; const val = k => esc(v[k] || "");
  return `<form id="listingForm" class="card"><div class="grid2"><div class="form-field"><label for="l-title">Job title</label><input id="l-title" name="title" required maxlength="200" value="${val("title")}" placeholder="Remote Administrative Assistant"></div>
<div class="form-field"><label for="l-company">Company (optional)</label><input id="l-company" name="company" maxlength="200" value="${val("company")}" placeholder="As the listing names it"></div></div>
<div class="form-field"><label for="l-desc">The listing</label><p class="hint">Paste the whole description: duties, pay, requirements and how to apply.</p><textarea id="l-desc" name="description" required maxlength="8000" placeholder="We are hiring part-time remote assistants, $500 weekly. No experience needed...">${val("description")}</textarea></div>
<div class="grid2"><div class="form-field"><label for="l-url">Apply link (optional)</label><p class="hint">We read the link, we don't open it.</p><input id="l-url" name="url" maxlength="2000" value="${val("url")}" placeholder="https://..."></div>
<div class="form-field"><label for="l-contact">Contact email (optional)</label><p class="hint">The address the listing says to write to.</p><input id="l-contact" name="contact" maxlength="200" value="${val("contact")}" placeholder="hr@company.com"></div></div>
<div class="row"><button class="b" type="submit">${icon("shield", 16)} Check this listing</button><span class="small faint">Or try a sample:</span>${LISTING_SAMPLES.map((s, i) => `<button class="b sm sec" type="button" data-do="lsample" data-i="${i}">${esc(s[0])}</button>`).join("")}</div></form>`;
}
const kindTabs = kind => `<div class="seg" role="tablist" style="margin-bottom:16px"><a href="#" data-go="scam"${kind === "listing" ? ' class="on" aria-current="page"' : ""}>A job listing</a><a href="#" data-go="scam?kind=message"${kind === "message" ? ' class="on" aria-current="page"' : ""}>A message</a></div>`;
const SAMPLES = [
  ["Fake professor", "Hi! I'm Dr. Carter from the Biology department. I need a personal assistant for $400 weekly, only a few hours. Text me at 850-555-0199 from your personal email, not your fsu.edu account.", "dr.carter.fsu@gmail.com"],
  ["Check scam", "Congratulations! You've been approved for a remote data entry role. We will mail you a check to purchase your equipment from our vendor. Deposit it and send the rest via Zelle.", ""],
  ["Real recruiter", "Hi Jordan, thanks for applying to the Marketing Data Analyst role at Garnet Analytics. Are you free for a 30-minute video interview next Tuesday or Wednesday afternoon? - Pat Lee, Campus Recruiter", "pat.lee@garnetanalytics.example"],
];
P.scam = () => {
  if (S.route.q.kind !== "message" && !S.route.q.m) {          // a job listing is the default tab
    const v = S.listingIn, r = S.route.q.run && v ? checkListing(v) : null;
    const top = r ? (fullView() ? verdictHtml(r) : publicVerdictHtml(r) + schoolForm()) : "";
    return pageHead("Is this job listing a scam?", "Found a job on Handshake, LinkedIn, Indeed, Instagram or a flyer? Paste it and get the same scam check every listing on NoleCareerShield goes through.", "Scam check")
      + kindTabs("listing") + takeFlash() + top + (top ? '<h3 class="sec">Check another listing</h3>' : "") + listingForm(v);
  }
  const q = S.route.q; let top = "", text = q.text || "", sender = q.sender || "";
  if (q.m && me()) {
    const c = S.convos.find(c => c.messages.some(m => m.id === q.m)), m = c && c.messages.find(x => x.id === q.m);
    if (m && (c.student === me().id || c.employer === me().id) && m.from !== me().id && m.status === "delivered")
      top = `<div class="card"><div class="eyebrow">The message you're checking</div><p style="white-space:pre-wrap;margin-top:6px">${esc(m.body)}</p><a class="small" href="#" data-go="messages?c=${c.id}">← Back to the conversation</a></div>` + verdictHtml(N.check(m.body), m.from === c.employer ? m.from : 0);
  } else if (q.run) { const r = N.check(text, sender); top = fullView() ? verdictHtml(r) : publicVerdictHtml(r) + schoolForm(); }
  const form = `<form id="scamForm" class="card"><div class="form-field"><label for="c-text">The message</label><p class="hint">Paste the whole thing: text, email, LinkedIn or Handshake DM. Nothing is saved.</p>
<textarea id="c-text" name="text" required maxlength="8000" placeholder="Hi! I'm Dr. Smith from the Psychology Department. I'm looking for a personal assistant, $400 weekly...">${esc(text)}</textarea></div>
<div class="form-field"><label for="c-sender">Who sent it (optional)</label><p class="hint">The email address or name it came from. It helps spot fake FSU and company addresses.</p><input id="c-sender" name="sender" maxlength="200" value="${esc(sender)}" placeholder="e.g. careers.fsu.edu@gmail.com"></div>
<div class="row"><button class="b" type="submit">${icon("shield", 16)} Check it</button><span class="small faint">Or try a sample:</span>${SAMPLES.map((s, i) => `<button class="b sm sec" type="button" data-do="sample" data-i="${i}">${esc(s[0])}</button>`).join("")}</div></form>
<p class="aimode" style="margin-top:8px">Rule set ${esc(N.ruleset)}. The same text always gets the same verdict. On the live site, an optional AI second opinion can add caution but never lower it.</p>`;
  return pageHead("Is this message a scam?", "Paste any message about a job, internship or gig. You'll get a clear verdict, the evidence behind it, and what to do next.", "Scam check") + kindTabs("message") + takeFlash() + top + (top ? '<h3 class="sec">Check another message</h3>' : "") + form;
};

// ---- career assistant (mirrors assistant.py: saved chats, cards from live approved listings, qualifications block) ----
const CS_STARTERS = [["search", "Find jobs matching my skills"], ["file", "Draft my resume"], ["chat", "Help me prepare for an interview"], ["shield", "Is this message a scam?"]];
const CS_SHOW_FIRST = 4;
ICONS.search = '<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/>';
ICONS.clock = '<path d="M4 12a8 8 0 1 0 2.5-5.8"/><path d="M4 4.5V8h3.5"/><path d="M12 8v4.5l3 1.5"/>';
ICONS.x = '<path d="M6 6l12 12M18 6 6 18"/>';
const csGreeting = first => { const h = new Date().getHours(), part = h >= 5 && h < 12 ? "Good morning" : h >= 12 && h < 17 ? "Good afternoon" : "Good evening"; return first ? `${part}, ${first}` : part; };
const csChats = () => (S.chats || []).filter(c => c.user === me().id).sort((a, b) => b.at - a.at || b.id - a.id);
const csChat = id => (S.chats || []).find(c => c.id === id && c.user === me().id);
function csFollow(out, hasJobs) {
  if (out.scam) return ["What should I do if I already replied?", "Find jobs matching my skills", "Help me prepare for an interview"];
  if (out.handoff === "resume") return ["Review my resume", "Find jobs matching my skills", "Help me prepare for an interview"];
  if (out.interview) return ["Find jobs matching my skills", "Review my resume", "Is this message a scam?"];
  if (hasJobs) return ["Show only remote jobs", "Show only part-time jobs", "Show internships", "Review my resume"];
  return ["Find jobs matching my skills", "Remote jobs", "Part-time jobs near campus"];
}
function csCard(j, p, ready) {
  const tags = (j.easy_apply ? '<span class="cs-tag ea">Quick apply</span>' : "") + ((j.age_days || 0) < 7 ? '<span class="cs-tag nw">New</span>' : "");
  const match = ready ? `<span class="pill accent">${N.fitScore(j, p).score}% match</span>` : "";
  const loc = j.location || (j.work_type === "remote" ? "Remote" : "");
  const pill = j.scam_status === "clear" ? '<span class="badge verified">✓ Scam check passed</span>' : '<span class="badge warning">⚠ Check carefully</span>';
  return `<article class="cs-job">${tags ? `<div class="cs-tags">${tags}</div>` : ""}<a class="cs-title" href="#" data-go="job?id=${j.id}">${esc(j.title)}</a><div class="cs-co">${esc(j.company)}</div>${loc ? `<div class="cs-loc">${esc(loc)}</div>` : ""}<div class="cs-meta"><span class="chip">${esc(cap(j.work_type))}</span>${match}${pill}</div></article>`;
}
function csQuals(j, p) {
  const items = N.fitScore(j, p).checklist.slice(0, 8); if (!items.length) return "";
  const met = items.filter(i => i.status === "met").length;
  const lead = met === items.length ? "You match all of the qualifications." : met * 2 > items.length ? "You match most qualifications." : met ? "You match some qualifications." : "You don't match these qualifications yet.";
  const sym = {met: ["✓", "met", "You have"], missing: ["⊘", "miss", "Not shown yet"], unknown: ["?", "unk", "Unknown"]};
  return `<section class="cs-quals"><h3>What they’re looking for <small>${esc(j.title)} at ${esc(j.company)}</small></h3><p>${lead}</p><ul>${items.map(i => `<li class="${sym[i.status][1]}"><span class="mk" aria-hidden="true">${sym[i.status][0]}</span><span class="sr">${sym[i.status][2]}: </span>${esc(i.text)}</li>`).join("")}</ul><p class="cs-note">Matching is based on your profile. <a href="#" data-go="setup?step=1">Update profile</a>.</p></section>`;
}
const csThumb = k => `<svg class="ic" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${k === "up" ? '<path d="M7 11v9H4v-9zM7 11l4-7c1.5 0 2.5 1 2.2 2.6L12.7 10H19a1.6 1.6 0 0 1 1.6 2l-1.5 6.2A2 2 0 0 1 17.2 20H7"/>' : '<path d="M7 13V4H4v9zM7 13l4 7c1.5 0 2.5-1 2.2-2.6L12.7 14H19a1.6 1.6 0 0 0 1.6-2l-1.5-6.2A2 2 0 0 0 17.2 4H7"/>'}</svg>`;
function csReply(m, cid, p, ready, latest) {
  const live = new Map(approvedJobs().map(j => [j.id, j])), jobs = (m.jobs || []).map(i => live.get(i)).filter(Boolean);
  let body = "";
  if (jobs.length) {
    const cards = jobs.map(j => csCard(j, p, ready));
    body += `<div class="cs-grid">${cards.slice(0, CS_SHOW_FIRST).join("")}</div>`;
    if (cards.length > CS_SHOW_FIRST) body += `<details class="cs-more"><summary><span class="more">Show more (${cards.length - CS_SHOW_FIRST})</span><span class="less">Show less</span> <svg class="ic" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg></summary><div class="cs-grid">${cards.slice(CS_SHOW_FIRST).join("")}</div></details>`;
  }
  body += `<div class="cs-text">${esc(m.text)}</div>`;
  if (m.handoff === "resume") body += `<p><a class="b" href="#" data-go="resume">${icon("file", 16)} Open Resume studio</a></p>`;
  if (m.scam) body += '<p><a class="b sec sm" href="#" data-go="scam?kind=message">Open Scam check</a></p>';
  if (jobs.length && ready) body += csQuals(jobs[0], p);
  else if (jobs.length) body += '<p class="cs-note">Set up your profile and each card shows how well you match. <a href="#" data-go="setup?step=1">Set up profile</a>.</p>';
  const fb = (k, v, label) => `<button class="cs-ic${m.feedback === v ? " on" : ""}" type="button" data-do="cs-fb" data-m="${m.id}" data-v="${k}" aria-label="${label}" aria-pressed="${m.feedback === v}">${csThumb(k)}</button>`;
  body += `<div class="cs-acts">${fb("up", 1, "Good answer")}${fb("down", -1, "Not helpful")}<button class="cs-ic" type="button" data-do="cs-copy" data-m="${m.id}" aria-label="Copy this answer" title="Copy">${icon("file", 17)}</button></div>`;
  if (latest && m.follow && m.follow.length) body += `<div class="cs-follow">${m.follow.map(f => `<button class="cs-chip" type="button" data-do="cs-ask" data-q="${esc(f)}">${esc(f)}</button>`).join("")}</div>`;
  return `<div class="cs-bot" id="m${m.id}">${body}</div>`;
}
const csAskForm = big => `<form class="cs-ask${big ? " big" : ""}" id="askForm"><label class="hp" for="cs-q">Message</label><input id="cs-q" name="q" type="text" required maxlength="4000" placeholder="${big ? "Ask anything…" : "Message…"}" autocomplete="off"><button class="cs-send" type="submit" aria-label="Send">${icon("send", 16)}</button></form><p class="cs-disc">AI-generated content may contain mistakes.</p>`;
P.assistant = () => {
  if (!isStudent()) return needStudent("the career assistant");
  const p = SP(me().id), ready = studentReady(p), first = (p.display_name || "").split(" ")[0], chats = csChats(), cid = S.chatId, chat = cid ? csChat(cid) : null;
  const items = chats.map(c => `<li${chat && c.id === chat.id ? ' class="on"' : ""}><a href="#" data-do="cs-open" data-id="${c.id}"><span class="t">${esc(c.title || "New chat")}</span><span class="d">${esc(ago(c.at))}</span></a><button class="cs-del" type="button" data-do="cs-del" data-id="${c.id}" aria-label="Delete chat ${esc(c.title)}">${icon("x", 14)}</button></li>`).join("");
  const side = `<aside class="cs-side"><div class="cs-brand">${icon("spark", 20)} <span>Career assistant</span></div><a class="cs-new" href="#" data-do="cs-new">${icon("plus", 16)} New chat</a><div class="cs-hist">${icon("clock", 15)} Chat history</div>${chats.length ? `<ul class="cs-list">${items}</ul>` : '<p class="cs-empty">Your chats show up here.</p>'}</aside>`;
  const setup = ready ? "" : banner("info", 'Set up your profile for personal matches. <a href="#" data-go="setup?step=1">Set up profile</a>', true);
  let main;
  if (!chat) {
    const recent = chats[0] ? `<a class="cs-chip" href="#" data-do="cs-open" data-id="${chats[0].id}">${icon("clock", 16)} <b>Recent:</b> ${esc(chats[0].title)} <small>${esc(ago(chats[0].at))}</small></a>` : "";
    main = `<div class="cs-home"><h1>${icon("spark", 30)} ${esc(csGreeting(first))}</h1><p class="cs-sub">What can I help you with today?</p>${csAskForm(true)}<div class="cs-chips">${recent}${CS_STARTERS.map(([ic, t]) => `<button class="cs-chip" type="button" data-do="cs-ask" data-q="${esc(t)}">${icon(ic, 16)} ${esc(t)}</button>`).join("")}</div><p class="aimode">Built-in matching · answers only from approved listings. On the live site this runs on Claude when an API key is set.</p></div>`;
  } else {
    const lastBot = [...chat.msgs].reverse().find(m => m.role === "assistant"), pending = chat.msgs.length && chat.msgs[chat.msgs.length - 1].role === "user";
    const parts = chat.msgs.map(m => m.role === "user" ? `<div class="cs-me">${esc(m.text)}</div>` : csReply(m, chat.id, p, ready, m === lastBot && !pending));
    if (pending) parts.push('<div class="cs-think" role="status"><span class="dots" aria-hidden="true"><i></i><i></i><i></i></span> Thinking…</div>');
    main = `<div class="cs-scroll">${parts.join("")}<div id="latest"></div></div><div class="cs-bar">${csAskForm(false)}</div>`;
  }
  return setup + `<div class="cs">${side}<section class="cs-main">${main}</section></div>`;
};
function ask(q) {
  q = (q || "").trim().slice(0, 4000); if (!q || !me()) return;
  if (!S.chats) S.chats = [];
  let chat = S.chatId ? csChat(S.chatId) : null;
  if (chat && chat.msgs.length && chat.msgs[chat.msgs.length - 1].role === "user") return;     // still waiting on an answer
  if (!chat) { chat = {id: S.nextChat = (S.nextChat || 0) + 1, user: me().id, title: q.length <= 60 ? q : q.slice(0, 57).trimEnd() + "…", at: NOW(), msgs: []};
    S.chats.push(chat); if (csChats().length > 60) S.chats = S.chats.filter(c => c.user !== me().id || csChats().slice(0, 60).includes(c)); S.chatId = chat.id; }
  chat.msgs.push({id: S.nextMsg = (S.nextMsg || 0) + 1, role: "user", text: q}); chat.at = NOW(); render(true);
  const uid = me().id;
  S.timers.push(setTimeout(() => {                      // the short beat is the engine running in your browser, not made-up latency
    if (!me() || me().id !== uid || !csChat(chat.id)) return;
    const out = N.assistant(chat.msgs.filter(m => m.role === "user").pop().text, SP(uid), approvedJobs());
    const ids = (out.jobs || []).map(r => r.job.id);
    chat.msgs.push({id: S.nextMsg = (S.nextMsg || 0) + 1, role: "assistant", text: out.reply, jobs: ids, scam: !!out.scam, handoff: out.handoff || "", follow: csFollow(out, ids.length > 0), feedback: 0});
    chat.at = NOW(); S.scrollTo = "latest"; render(true);
  }, 500));
}

// ---- resume studio: optimizer (mirrors resume_tools.py: _landing, _report_page, _sugg_card, _tailor_html, accept) ----
const RS_TABS = [["optimize", "Optimize"], ["review", "Score details"], ["edit", "Edit"], ["tailor", "Tailor to a job"], ["versions", "Versions"]];
const rsTabs = active => `<div class="seg rs-tabs" role="tablist">${RS_TABS.map(([k, v]) => `<a href="#" data-go="resume${k === "optimize" ? "" : "?tab=" + k}"${k === active ? ' class="on" aria-current="page"' : ""}>${v}</a>`).join("")}</div>`;
const rsChecks = items => `<ul class="rs-checks">${items.map(i => `<li><span class="tick">${icon("check", 14)}</span><span>${i}</span></li>`).join("")}</ul>`;
const rsNorm = s => String(s || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
function rsSources(p) {
  const out = [];
  if (p.resume_text) out.push({key: "main", name: p.resume_name || "My resume", kind: "Main resume", text: p.resume_text});
  S.versions.filter(v => v.user === me().id).forEach(v => out.push({key: "v" + v.id, name: v.name, kind: "Tailored copy", at: v.at, text: v.body}));
  return out;
}
function rsLanding(p) {
  const srcs = rsSources(p);
  const card = srcs.length ? `<h2>Add your resume</h2><p class="sub">Select a saved resume or upload a new one.</p>
<form id="rsPick"><label class="hp" for="rs-src">Saved resume</label><select id="rs-src" name="src">${srcs.map(x => `<option value="${esc(x.key)}">${esc(x.name)} (${esc(x.kind.toLowerCase())})</option>`).join("")}</select>
<p class="rs-pickmeta">${esc(srcs[0].name)}</p><button class="b rs-go" type="submit">Optimize my resume</button></form>
<div class="or"><span>or</span></div><details class="rs-up"><summary>${icon("plus", 16)} Upload resume</summary><div class="inner">${rsUpload("Upload and optimize")}</div></details>`
    : `<h2>Add your resume</h2><p class="sub">Upload a file or paste it, and we'll check it for ATS readiness.</p>${rsUpload("Optimize my resume", true)}`;
  const tools = srcs.length ? `<div class="rs-tools">
<a class="card rs-tool" href="#" data-go="resume?tab=tailor">${icon("jobs", 20)}<b>Tailor to a job</b><span>Pick a listing and see which of its qualifications your resume covers.</span></a>
<a class="card rs-tool" href="#" data-go="resume?src=main#rs-stand">${icon("spark", 20)}<b>Help me stand out</b><span>A few tips drawn from what your resume already says.</span></a>
<a class="card rs-tool" href="#" data-go="resume?tab=edit">${icon("file", 20)}<b>Edit and versions</b><span>Edit the text, copy it, or reopen a saved version.</span></a></div>` : "";
  return (srcs.length ? rsTabs("optimize") : "") + takeFlash() + `<section class="rs-hero"><div><div class="rs-badge">${icon("spark", 28)}</div>
<h1 class="rs-h1">Land more interviews with an ATS-ready resume</h1>
<p class="rs-lede">Most employers screen resumes with software first. We check yours for the same things, then suggest fixes in your own words.</p>
${rsChecks(["Scored on formatting, keywords, impact and contact details", "<b>You approve every change.</b> Nothing is applied until you click Accept", "Suggestions rephrase what you wrote. They never make things up"])}</div>
<div class="card rs-add">${card}<p class="rs-fine">Runs on the built-in reviewer, right in your browser. On the live site, optional AI features use Claude only when you press an AI button. Review every suggestion so it accurately reflects your own experience.</p></div></section>${tools}`;
}
function rsUpload(button, first) {
  return `<form id="resumeUpload"><div class="form-field"><label for="r-file">Upload a file</label><p class="hint">PDF, Word (.docx) or text, up to 2 MB. It's read right here in your browser and only the text is kept.</p><input id="r-file" type="file" name="file" accept=".pdf,.docx,.txt,.md,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain"></div>
<div class="form-field"><label for="r-paste">Or paste it</label><textarea id="r-paste" name="paste" maxlength="20000" placeholder="Paste your resume text"></textarea></div>
<div class="row"><button class="b" type="submit">${button}</button>${first ? '<button class="b sec" type="button" data-do="sample-resume">Use a sample resume</button>' : ""}</div></form>`;
}
function rsCard(sg, ctx, canAccept, canDismiss) {
  const sev = {bad: ["bad", "Fix"], warn: ["warn", "Improve"], info: ["info", "Tip"]}[sg.severity || "info"];
  let diff = "", accept = "";
  if (sg.kind === "rewrite") diff = `<div class="rs-diff"><div class="was"><span class="lbl">Now</span>${esc(sg.old)}</div><div class="now"><span class="lbl">Suggested</span>${esc(sg.new)}</div></div>`;
  else if (sg.kind === "skills") diff = `<div class="rs-diff"><div class="now"><span class="lbl">Adds to your Skills</span>${esc(sg.new)}</div></div>`;
  else if (sg.kind === "summary") diff = `<div class="rs-diff"><div class="now"><span class="lbl">Adds a summary</span>${esc(sg.new)}</div></div>`;
  if (["rewrite", "skills", "summary"].includes(sg.kind) && canAccept) accept = `<button class="b sm" type="button" data-do="accept" data-ctx="${esc(ctx)}" data-sid="${esc(sg.id)}">Accept</button>`;
  const note = sg.kind === "rewrite" ? '<span class="small">Fill in any [placeholder] after.</span>' : sg.kind === "tip" ? '<a class="small" href="#" data-go="resume?tab=edit">Edit my resume</a>' : "";
  const dis = canDismiss ? `<button class="b sm ghost" type="button" data-do="dismiss" data-ctx="${esc(ctx)}" data-sid="${esc(sg.id)}">${accept ? "Dismiss" : "Got it"}</button>` : "";
  const why = sg.detail && sg.kind !== "skills" ? `<div class="why">${esc(sg.detail)}</div>` : "";
  return `<div class="rs-card${sg.kind === "tip" ? " tip" : ""}"><h4><span class="pill ${sev[0]}">${sev[1]}</span> ${esc(sg.title)}</h4>${why}${diff}<div class="rs-actions">${accept}${dis}${note}</div></div>`;
}
function rsReport(p, src) {
  const srcs = rsSources(p), cur = srcs.find(c => c.key === src);
  if (!cur) return rsTabs("optimize") + '<div class="banner info" role="status">That resume isn\'t available. Pick another.</div>' + rsLanding(p);
  const rp = N.report(cur.text, p.skills), gone = S.dismissed[cur.key] || (S.dismissed[cur.key] = new Set());
  S.suggs = Object.fromEntries(rp.suggestions.map(s => [s.id, s]));
  const by = {}; rp.sections.forEach(s => { by[s.key] = []; }); rp.suggestions.forEach(s => by[s.section].push(s));
  const openN = k => by[k].filter(s => !gone.has(s.id)).length, tone = {ok: " ok", warn: " warn", "": ""};
  const nav = rp.sections.map(sc => `<a href="#" data-go="resume?src=${cur.key}#rs-${sc.key}"><span>${esc(sc.name)}</span><span class="pc">${sc.percent}%</span><div class="meter${tone[sc.tone]}"><i style="width:${sc.percent}%"></i></div><span class="open">${openN(sc.key)} suggestion${openN(sc.key) === 1 ? "" : "s"} open</span></a>`).join("");
  const secs = rp.sections.map(sc => {
    const list = by[sc.key], cards = list.filter(s => !gone.has(s.id)).map(s => rsCard(s, cur.key, true, true)).join("")
      || `<div class="rs-clear">${list.length ? "You dismissed every suggestion here." : "Nothing to fix here. Nice."}</div>`;
    const n = list.filter(s => gone.has(s.id)).length;
    return `<section id="rs-${sc.key}"><div class="rs-sech"><h3>${esc(sc.name)}</h3><span class="pill ${sc.tone || "info"}">${sc.percent}%</span></div>${cards}${n ? `<p class="rs-dis">${n} dismissed. <button class="linkbtn" type="button" data-do="undismiss" data-ctx="${esc(cur.key)}">Show all again</button></p>` : ""}</section>`;
  }).join("");
  const tips = N.standOut(cur.text).map(t => `<div class="rs-card tip"><h4>${icon("spark", 15)} ${esc(t.title)}</h4><div class="why">${esc(t.detail)}</div></div>`).join("");
  const ranked = N.rankJobs(approvedJobs(), p, "", 40);
  const tailor = ranked.length ? `<section id="rs-tailor"><div class="rs-sech"><h3>Tailor to a job</h3></div><div class="card" style="margin-top:10px"><p class="small muted" style="margin-bottom:10px">Pick a listing from the approved board. You'll see which of its listed qualifications your resume covers and get edits to accept or dismiss.</p>
<form id="rsJobPick" class="rs-pick"><div><label class="hp" for="rs-job">Job</label><select id="rs-job" name="job"><option value="">Choose a listing...</option>${ranked.map(r => `<option value="${r.job.id}">${esc(r.job.title)} · ${esc(r.job.company)}</option>`).join("")}</select></div><button class="b" type="submit">Show match details</button></form></div></section>` : "";
  const st = rp.stats;
  return rsTabs("optimize") + `<a class="rs-back" href="#" data-go="resume">&larr; Choose another resume</a>${takeFlash()}<div class="rs-report"><aside class="rs-side"><div class="card rs-score"><div class="eyebrow">ATS readiness</div>
<div class="ring" style="--p:${rp.percent}"><b>${rp.percent}<small>%</small></b></div><h2>${esc(rp.label)}</h2><p>${esc(cur.name)} · ${st.words} words · ${st.bullets} bullets</p><nav class="rs-nav" aria-label="Report sections">${nav}</nav></div></aside>
<div class="rs-main"><div class="rs-approve">${icon("shield", 18)}<span><b>You approve every change.</b> Nothing on your resume changes until you press Accept, and you can dismiss anything.</span></div>${secs}
<section id="rs-stand"><div class="rs-sech"><h3>Help me stand out</h3></div><div class="rs-stand">${tips || '<div class="rs-clear">Nothing to add right now.</div>'}</div></section>${tailor}
<div class="row" style="margin-top:8px"><a class="b sec" href="#" data-go="resume?tab=edit">Edit resume</a></div></div></div>`;
}
function rsWorking(p, jid) {
  const v = jid ? S.versions.find(x => x.user === me().id && x.job === jid) : null;
  return [v ? v.body : (p.resume_text || ""), v || null];
}
function rsTailor(p, jid, title, desc) {
  const [text, wv] = rsWorking(p, jid), job = jid ? Object.assign({}, S.jobs.find(x => x.id === jid) || {}, {title, description: desc}) : {title, description: desc};
  const t = N.tailor(text, title, desc, p), prof = Object.assign({}, p, {skills: [], items: [], headline: "", bio: "", resume_text: text}), f = N.fitScore(job, prof);
  const counted = f.checklist.filter(c => c.status === "met" || c.status === "missing"), met = counted.filter(c => c.status === "met").length;
  const pct = f.percent != null ? f.percent : counted.length ? Math.round(100 * met / counted.length) : f.score;
  const li = c => `<li class="${c.status}"><span class="st">${MARK[c.status]}</span><div>${esc(c.text)}${c.evidence ? `<span class="ev">${esc(c.evidence)}</span>` : ""}</div></li>`;
  const covered = f.checklist.filter(c => c.status === "met").map(li).join(""), notyet = f.checklist.filter(c => c.status !== "met").map(li).join("");
  const headline = counted.length ? `Your resume covers ${met} of ${counted.length} listed qualifications.` : "This posting doesn't list specific qualifications, so this uses the skills and keywords in its text.";
  const ring = counted.length ? pct : t.match, company = jid && job.company ? ` · <a href="#" data-go="job?id=${jid}">${esc(job.company)}</a>` : "";
  const head = `<div class="card"><div class="rs-job"><div class="ring" style="--p:${ring}"><b>${ring}<small>%</small></b></div><div><div class="eyebrow">Match details</div><h2>${esc(title || "This job")}</h2><p class="small muted">${esc(headline)}${company}</p></div></div>
<div class="rs-cover"><div><h4>Covered by your resume</h4><ul class="checklist">${covered || '<li class="unknown"><span class="st">?</span><div>Nothing listed is covered yet.</div></li>'}</ul></div>
<div><h4>Not shown yet</h4><ul class="checklist">${notyet || '<li class="met"><span class="st">✓</span><div>Every listed qualification is covered.</div></li>'}</ul></div></div>
${wv ? `<p class="rs-note">You're working on your tailored copy “${esc(wv.name)}”. Your main resume isn't changed.</p>` : ""}</div>`;
  const sugg = [], jobSk = N.extractSkills(`${title}\n${desc}`);
  if (!rsNorm(text).includes(rsNorm(t.summary).slice(0, 60))) sugg.push({kind: "summary", severity: "info", title: "Add a summary written for this role", detail: "", old: "", new: t.summary});
  const miss = N.missingProfileSkills(text, (p.skills || []).filter(s => jobSk.includes(s)));
  if (miss.length) sugg.push({kind: "skills", severity: "warn", title: "Add skills this job lists that you already have on your profile", detail: "", old: "", new: miss.join(", ")});
  t.lead_bullets.slice(0, 3).forEach(b => sugg.push({kind: "tip", severity: "info", title: "Lead with: " + b.text.slice(0, 110), detail: b.why, old: "", new: ""}));
  sugg.forEach((s, i) => { s.id = "s" + i; });
  S.suggs = Object.fromEntries(sugg.map(s => [s.id, s]));
  const key = "job" + jid, gone = S.dismissed[key] || (S.dismissed[key] = new Set());
  const cards = sugg.filter(s => !gone.has(s.id)).map(s => rsCard(s, key, !!jid, !!jid)).join("") || '<div class="rs-clear">No edits to suggest right now.</div>';
  const n = sugg.filter(s => gone.has(s.id)).length;
  const edits = `<section style="margin-top:22px"><div class="rs-sech"><h3>Suggested edits</h3></div><div class="rs-approve" style="margin-top:8px">${icon("shield", 18)}<span><b>You approve every change.</b> Nothing is applied until you press Accept.</span></div>${cards}
${jid && n ? `<p class="rs-dis">${n} dismissed. <button class="linkbtn" type="button" data-do="undismiss" data-ctx="${key}">Show all again</button></p>` : ""}${jid ? "" : '<p class="rs-note">To accept edits, choose a listing from the board. For a pasted description, save a tailored copy below and edit it there.</p>'}</section>`;
  const pills = (xs, cls) => xs.map(x => `<span class="pill ${cls}">${esc(x)}</span>`).join("") || '<span class="faint small">None</span>';
  const detail = `<details class="card" style="margin-top:16px"><summary class="small" style="cursor:pointer;font-weight:600;color:var(--accent-ink)">Skills and keywords in this posting</summary>
<div class="split" style="margin-top:12px"><div><b class="small">Skills you show</b><div class="kw" style="margin-top:6px">${pills(t.skills_present, "ok")}</div></div><div><b class="small">Skills they want that your resume doesn't show</b><div class="kw" style="margin-top:6px">${pills(t.skills_missing, "warn")}</div></div></div>
<div style="margin-top:12px"><b class="small">Keywords to use where true</b><div class="kw" style="margin-top:6px">${pills(t.keywords_missing, "")}</div></div></details>`;
  const save = wv ? "" : `<form id="versionForm" class="card" style="margin-top:16px"><input type="hidden" name="job_id" value="${jid}"><div class="form-field"><label for="v-name">Save a tailored copy</label><p class="hint">Adds the summary to a copy. Your main resume doesn't change.</p><input id="v-name" name="name" maxlength="80" value="${esc(("For " + title).slice(0, 80))}"></div>
<details style="margin:-4px 0 14px"><summary class="small" style="cursor:pointer;color:var(--accent-ink);font-weight:600">Preview and edit the copy before saving</summary><textarea class="resume" name="body" maxlength="20000" style="margin-top:8px" aria-label="Tailored copy">${esc(N.setSummary(text, t.summary))}</textarea></details><button class="b" type="submit">Save version</button></form>`;
  return head + edits + detail + save;
}
function rsWorkText(ctx, p) {
  if (ctx === "main") return {get: () => p.resume_text, set: t => { p.resume_text = t; }};
  const jm = /^job(\d+)$/.exec(ctx), vm = /^v(\d+)$/.exec(ctx);
  if (vm) { const v = S.versions.find(x => x.id === Number(vm[1]) && x.user === me().id); return v && {get: () => v.body, set: t => { v.body = t; }}; }
  if (jm) {
    const jid = Number(jm[1]), j = approvedJobs().find(x => x.id === jid); if (!j || !p.resume_text) return null;
    let v = S.versions.find(x => x.user === me().id && x.job === jid);
    if (!v) { v = {id: Date.now(), user: me().id, name: ("For " + j.title + " at " + j.company).slice(0, 80), body: p.resume_text, job: jid, at: NOW()}; S.versions.unshift(v); if (S.versions.filter(x => x.user === me().id).length > 10) { const mine = S.versions.filter(x => x.user === me().id); S.versions.splice(S.versions.indexOf(mine[mine.length - 1]), 1); } }
    return {get: () => v.body, set: t => { v.body = t; }};
  }
  return null;
}
function rsAccept(ctx, sid) {
  const p = SP(me().id), sg = (S.suggs || {})[sid], w = rsWorkText(ctx, p); if (!sg || !w) return;
  const text = w.get(), news = String(sg.new || "").replace(/\s+/g, " ").trim(); let after = text;
  if (sg.kind === "rewrite" && text.includes(sg.old) && news && news.length <= 600) after = text.replace(sg.old, () => news);
  else if (sg.kind === "skills") after = N.addSkills(text, p.skills || []);
  else if (sg.kind === "summary" && /^job/.test(ctx) && news && news.length <= 600) after = N.setSummary(text, news);
  if (after !== text) { w.set(after.slice(0, 20000)); flash("verified", /^job/.test(ctx) ? "Applied to your tailored copy. Your main resume is unchanged." : "Applied. Your other suggestions are still here, and the score is updated."); }
  delete S.dismissed[ctx]; render(true);
}

// ---- resume studio ----
P.resume = () => {
  if (!isStudent()) return needStudent("the resume studio");
  const p = SP(me().id), tab = ["optimize", "review", "edit", "tailor", "versions"].includes(S.route.q.tab) ? S.route.q.tab : "optimize";
  const head = pageHead("Resume studio", "Score it, fix it line by line, and tailor it to any job on the board. Suggestions rephrase what you wrote; they never make things up.", "Resume") + takeFlash();
  if (!p.resume_text && !rsSources(p).length || tab === "optimize" && !S.route.q.src) return rsLanding(p);
  if (tab === "optimize") return rsReport(p, /^(main|v\d+)$/.test(S.route.q.src) ? S.route.q.src : "main");
  const tabs = rsTabs(tab);
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
    if (sel) { const j = approvedJobs().find(x => x.id === sel); result = j ? rsTailor(p, sel, j.title, j.description) : '<div class="banner warning" role="alert">That listing isn\'t available anymore.</div>'; }
    else if (S.tailor) result = rsTailor(p, 0, S.tailor.title, S.tailor.desc);
    return head + tabs + `<form id="tailorForm" class="card"><div class="form-field"><label for="t-job">A job on the board</label><select id="t-job" name="job_id"><option value="">Choose a listing...</option>${ranked.map(r => `<option value="${r.job.id}"${r.job.id === sel ? " selected" : ""}>${esc(r.job.title)} · ${esc(r.job.company)} (fit ${r.fit ? r.fit.score : r.score})</option>`).join("")}</select></div>
<div class="or"><span>Or paste a job description</span></div><div class="form-field"><label for="t-title">Job title</label><input id="t-title" name="title" maxlength="200" placeholder="Marketing Intern"></div>
<div class="form-field"><label for="t-desc">Job description</label><textarea id="t-desc" name="description" maxlength="8000" placeholder="Paste the posting"></textarea></div><button class="b" type="submit">Show match details</button></form><div style="margin-top:18px">${result}</div>${note}`;
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
    `<div class="inbox${c ? " open" : ""}"><div class="threads">${threads}</div>${right}</div><p class="small faint" style="margin-top:10px">Links in messages aren't clickable. Never send money, gift cards or bank details to get a job. <a href="#" data-go="scam?kind=message">Check a message</a></p>`;
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
  if (!p.visible && !S.convos.some(c => c.student === to && c.employer === sender.id) && !S.apps.some(a => a.student === to && a.employer === sender.id)) return [false, "That student isn't accepting messages from employers."];
  return [true, ""];
}
const REPLIES = ["Thanks for reaching out! I'll take a look and get back to you by the end of the week.", "Great to hear from you. Could you send your resume through our careers page so HR has it on file?",
  "Thanks! Are you available for a quick 15-minute call Thursday or Friday afternoon?"];
function sendMessage(c, text) {
  const m = addMsg(c, me().id, text);
  if (m.status === "held") flash("warning", "Your message was held for a safety review because it matched scam patterns. A reviewer checks it before it's delivered.");
  else {
    const other = c.student === me().id ? c.employer : c.student;
    mail(U(other).email, "You have a new message on NoleCareerShield", `${who(me().id)[0]} sent you a message on NoleCareerShield.\n\nRead it on the site. We never put message text in emails, so an email that includes a "message" and asks you to reply is not from us.`, null);
    if (isStudent() && !c.blocked_by) S.timers.push(setTimeout(() => { if (S.convos.includes(c) && !c.blocked_by) { addMsg(c, c.employer, REPLIES[c.messages.length % REPLIES.length]); if (S.route.name === "messages" || S.route.name === "home") render(true); else nav(); } }, 2600));
  }
}

// ---- feed ----
const KINDS = {question: "Question", advice: "Advice", opportunity: "Opportunity", event: "Event", win: "Win", info_session: "Info session"};
const KIND_PILL = {question: "info", advice: "gold", opportunity: "accent", event: "gold", win: "ok", info_session: "gold"};
// Mirrors feed.py: tabs (Feed / For you / Saved), pills (All / Your major / Employers), bookmark saves, for-you ranking, right rail.
const FEED_TABS = [["feed", "Feed"], ["foryou", "For you"], ["saved", "Saved"]], FEED_PILLS = [["all", "All"], ["major", "Your major"], ["employers", "Employers"]];
const FEED_RULES = ["Be kind and specific. Help each other out.", "No ads, spam or pay-to-apply offers.", "Never share passwords, SSNs or bank details.", "Report anything that feels like a scam."];
const FEED_STOP = new Set(("about above after again also always another anyone around because before being between both come could does doing done down each even ever every from get going good great have having here hello help how into just know like look make many more most much need only other over please really should some someone something still such take than thank thanks that their them then there these they thing think this those through today want week were what when where which while will with would year your students student fsu florida state university apply hiring internship internships").split(" "));
const MAX_SAVES = 300;
const bookmark = (filled, size) => `<svg class="ic" viewBox="0 0 24 24" width="${size || 20}" height="${size || 20}" fill="${filled ? "currentColor" : "none"}" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 4h12v17l-6-4.2L6 21z"/></svg>`;
const isSaved = (uid, pid) => S.saves.some(x => x.user === uid && x.post === pid);
function feedUrl(tab, f, q) { const p = []; if (tab && tab !== "feed") p.push("tab=" + tab); if (f && f !== "all") p.push("f=" + f); if (q) p.push("q=" + encodeURIComponent(q)); return "feed" + (p.length ? "?" + p.join("&amp;") : ""); }
function forYouScore(post, viewer, author, now) {   // author major +4, shared skills up to +3, viewer skills named in the post up to +3, their major named +2, recency up to +4 (halves every 3 days)
  let pts = 0; const vmajor = (viewer.major || "").trim().toLowerCase(), vskills = (viewer.skills || []).filter(Boolean), body = post.body.toLowerCase();
  if (author && vmajor && (author.major || "").trim().toLowerCase() === vmajor) pts += 4;
  if (author) { const theirs = new Set((author.skills || []).map(x => x.toLowerCase())); pts += Math.min(3, vskills.filter(x => theirs.has(x.toLowerCase())).length); }
  pts += Math.min(3, vskills.filter(w => new RegExp("(?<![a-z0-9])" + w.toLowerCase().replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "(?![a-z0-9])").test(body)).length);
  if (vmajor && body.includes(vmajor)) pts += 2;
  return pts + 4 * Math.pow(0.5, Math.max(0, now - post.at) / 864e5 / 3);
}
function feedTrending() {
  const since = NOW() - 30 * 864e5, seen = {};
  S.posts.filter(p => p.status === "published" && p.at > since).slice(-300).forEach(p => new Set((p.body.match(/#?[A-Za-z][A-Za-z+#.-]{3,24}/g) || []).map(w => w.toLowerCase().replace(/^#/, "")).filter(w => !FEED_STOP.has(w))).forEach(w => { seen[w] = (seen[w] || 0) + 1; }));
  return Object.entries(seen).filter(([, n]) => n >= 2).sort((x, y) => y[1] - x[1] || (x[0] < y[0] ? -1 : 1)).slice(0, 5);
}
function feedAuthor(id) {
  const [n, sub, kind] = who(id), nm = `<a href="#" data-go="${kind === "emp" ? "company" : "u"}?id=${id}" style="text-decoration:none">${esc(n)}</a>`;
  return `<div class="person"><span class="avatar${kind === "emp" ? " emp" : ""}">${initials(n)}</span><div style="min-width:0"><div class="nm">${nm}${kind === "emp" ? ' <span class="pill accent fd-tag">Employer</span>' : ""}</div><div class="sub">${esc(sub)}</div></div></div>`;
}
function feedRail() {
  let people = "";
  if (isStudent()) {
    const rows = suggestions(me().id).slice(0, 3).map(([uid]) => `<div class="fd-person">${person(uid)}${connectButton(uid, "none", "feed", false)}</div>`)
      .concat(Object.keys(S.employers).map(Number).filter(e => approvedEmp(e) && !isFollowing(me().id, e)).slice(0, 2).map(e => `<div class="fd-person">${person(e)}${followButton(e, false, "feed")}</div>`)).join("");
    if (rows) people = `<section class="fd-card" aria-label="Suggested people"><h3>People to follow</h3>${rows}<p style="margin:8px 0 0"><a class="small" href="#" data-go="network?tab=discover">See more in your network</a></p></section>`;
  }
  const topics = feedTrending(), tcard = topics.length ? `<section class="fd-card" aria-label="Trending topics"><h3>Trending topics</h3><div class="fd-topics">${topics.map(([w, n]) => `<a href="#" data-go="${feedUrl("feed", "all", w)}">${esc(w)}<small>${n}</small></a>`).join("")}</div></section>` : "";
  return `<aside class="fd-rail" aria-label="Feed sidebar">${people}${tcard}<section class="fd-card" aria-label="Community guidelines"><h3>Community guidelines</h3><ul class="fd-rules">${FEED_RULES.map(g => `<li>${esc(g)}</li>`).join("")}</ul></section></aside>`;
}
P.feed = () => {
  if (!me()) return pageHead("The FSU feed", "Questions, advice and opportunities from verified FSU students and employers our reviewers approved.", "Community") +
    `<div class="bento"><div class="tile w3"><h3>Students</h3><p>Sign in with your @fsu.edu account to read and post.</p><div class="foot"><a class="b" href="#" data-go="start">Log in or sign up</a></div></div><div class="tile w3"><h3>Employers</h3><p>Approved employers can share internships, info sessions and advice for FSU students.</p><div class="foot"><a class="b sec" href="#" data-do="as-employer">Explore as a sample employer</a></div></div></div>`;
  if (isEmployer() && !approvedEmp(me().id)) return pageHead("The FSU feed", "", "Community") + banner("info", "The feed opens to employers once a reviewer approves your organization.");
  const rq = S.route.q, tab = ["feed", "foryou", "saved"].includes(rq.tab) ? rq.tab : "feed", meId = me().id;
  const f = FEED_PILLS.some(x => x[0] === rq.f) && !(rq.f === "major" && !isStudent()) ? rq.f : "all";
  const q = /^[A-Za-z0-9+#. -]{1,40}$/.test((rq.q || "").trim()) ? rq.q.trim() : "";
  const viewer = isStudent() ? (SP(meId) || {}) : {}, vmajor = (viewer.major || "").trim().toLowerCase();
  const visible = p => p.status === "published" || (p.author === meId && ["pending", "held", "rejected"].includes(p.status));
  let posts, lead = "", note = "", empty;
  if (tab === "saved") {
    posts = S.saves.filter(x => x.user === meId).sort((a, b) => b.at - a.at).map(x => S.posts.find(p => p.id === x.post)).filter(p => p && p.status === "published").slice(0, 100);
    empty = `<div class="fd-empty">${bookmark(false, 44)}<h2>No saved posts yet</h2><p>Tap the bookmark on any post to save it here for later.</p><a class="b sec" href="#" data-go="feed">Browse the feed</a></div>`;
  } else {
    posts = S.posts.filter(visible).filter(p => {
      if (f === "employers" && U(p.author) && U(p.author).role !== "employer") return false;
      if (f === "major" && !(vmajor && U(p.author) && U(p.author).role === "student" && ((SP(p.author) || {}).major || "").trim().toLowerCase() === vmajor)) return false;
      return !q || p.body.toLowerCase().includes(q.toLowerCase());
    });
    if (tab === "foryou") {
      const now = NOW(); posts = posts.map(p => [forYouScore(p, viewer, U(p.author) && U(p.author).role === "student" ? SP(p.author) : null, now), p]).sort((x, y) => y[0] - x[0] || y[1].at - x[1].at).map(x => x[1]).slice(0, 30);
      note = isStudent() ? `<p class="fd-note">Ranked by how much each post overlaps with your major and skills, then by how recent it is.${viewer.major ? "" : " Add your major and skills to your profile to sharpen it."}</p>` : '<p class="fd-note">Newest first. Students see posts ranked by their major and skills.</p>';
    } else posts.sort((a, b) => b.at - a.at);
    empty = f === "major" && isStudent() && !vmajor ? '<div class="fd-empty"><h2>Add your major</h2><p>Add your major to your profile and posts from students in it will show up here.</p><a class="b sec" href="#" data-go="setup">Update profile</a></div>'
      : f === "major" ? '<div class="fd-empty"><h2>No posts from your major yet</h2><p>When students in your major share something, it will show up here.</p></div>'
      : f === "employers" ? '<div class="fd-empty"><h2>No employer posts yet</h2><p>Approved employers share opportunities and advice for FSU students here.</p></div>'
      : '<div class="fd-empty"><h2>Nothing here yet</h2><p>Start the conversation.</p></div>';
    const pills = FEED_PILLS.filter(x => !(x[0] === "major" && !isStudent())).map(([k, label]) => `<a class="fd-pill" href="#" data-go="${feedUrl(tab, k, q)}"${k === f ? ' aria-current="true"' : ""}>${k === f ? icon("check", 15) : ""}${label}</a>`).join("")
      + (q ? `<a class="fd-pill" href="#" data-go="${feedUrl(tab, f)}">Topic: ${esc(q)} ✕</a>` : "");
    const kinds = isStudent() ? ["question", "advice", "opportunity", "event", "win"] : ["opportunity", "advice", "event", "info_session"];
    const d = S.feedDraft || {}, rule = isStudent() ? "Share a question, advice, a win, or an opportunity with other Noles." : "Employer posts must be opportunities, events or advice for FSU students. Ads and promotions are declined. A reviewer approves each post.";
    const canPost = isStudent() ? studentReady(SP(meId)) : true, [nm] = who(meId);
    const composer = canPost ? `<details class="fd-comp"${d.body ? " open" : ""}><summary><span class="avatar${isEmployer() ? " emp" : ""}" aria-hidden="true">${initials(nm)}</span><span>Share something with the community…</span></summary><form id="feedForm" class="composer-card">${takeFlash()}<label for="f-body" class="hp">Post</label><textarea id="f-body" name="body" required maxlength="1500" placeholder="${esc(rule)}">${esc(d.body || "")}</textarea>
<div class="row" style="margin-top:8px"><label for="f-kind" class="hp">Type</label><select id="f-kind" name="kind" style="width:auto">${kinds.map(k => `<option value="${k}"${d.kind === k ? " selected" : ""}>${KINDS[k]}</option>`).join("")}</select>
<label for="f-link" class="hp">Link</label><input id="f-link" name="link" maxlength="300" placeholder="Link (optional)" value="${esc(d.link || "")}" style="flex:1;min-width:160px"><button class="b" type="submit">Post</button></div>${isEmployer() ? `<p class="small faint" style="margin-top:6px">${esc(rule)}</p>` : ""}</form></details>` : banner("info", "Set up your profile (name and major) before posting.");
    lead = `<div class="fd-pills" role="group" aria-label="Filter posts">${pills}</div>${composer}`;
  }
  const here = tab === "saved" ? "feed?tab=saved" : feedUrl(tab, f, q);
  const items = posts.map(p => {
    const st = p.status !== "published" ? `<span class="pill ${p.status === "rejected" ? "bad" : "warn"}">${{pending: "Waiting for review", held: "Held for a safety check", rejected: "Not approved"}[p.status]}</span>` : "";
    const open = S.openComments === p.id, mine = p.author === meId, helped = p.helpful.has(meId), sv = isSaved(meId, p.id);
    const save = p.status === "published" ? `<button class="fd-save-b" type="button" data-do="${sv ? "unsave" : "save"}" data-id="${p.id}" data-next="${esc(here)}" aria-label="${sv ? "Remove from saved posts" : "Save post"}" title="${sv ? "Remove from saved posts" : "Save post"}" aria-pressed="${sv}">${bookmark(sv)}</button>` : "";
    return `<article class="post fd-post"><div class="fd-head">${feedAuthor(p.author)}<div class="fd-meta">${st}<span class="pill ${KIND_PILL[p.kind]} fd-tag">${KINDS[p.kind]}</span><span class="fd-time">${ago(p.at)}</span><span class="fd-save">${save}</span></div></div>
<div class="body">${esc(p.body)}</div>${p.link ? `<p class="lnk">${icon("jobs", 14)} <a href="${esc(p.link)}" target="_blank" rel="noopener noreferrer nofollow ugc">${esc(p.link.slice(0, 90))}</a> <span class="faint">(opens another site)</span></p>` : ""}
${p.status === "published" ? `<div class="acts"><button type="button" data-do="helpful" data-id="${p.id}"${helped ? ' class="on"' : ""}>Helpful · ${p.helpful.size}</button><button type="button" data-do="comments" data-id="${p.id}">Comments · ${p.comments.length}</button>${mine ? "" : `<button type="button" data-do="report-post" data-id="${p.id}">${p.reports.has(meId) ? "Reported" : "Report"}</button>`}${!mine && isStudent() && U(p.author).role === "employer" && approvedEmp(p.author) ? `<a href="#" data-go="newmsg?to=${p.author}">Message</a>` : ""}${mine ? `<button type="button" data-do="del-post" data-id="${p.id}">Delete</button>` : ""}</div>` : ""}
${open ? `<div class="comments">${p.comments.map(c => `<div class="comment"><b>${esc(who(c.author)[0])}</b> ${esc(c.body)} <span class="small faint">${ago(c.at)}</span></div>`).join("") || '<p class="faint small">No comments yet.</p>'}<form class="commentForm row" data-id="${p.id}" style="margin-top:8px"><label for="cm-${p.id}" class="hp">Comment</label><input id="cm-${p.id}" name="body" maxlength="500" required placeholder="Add a comment" style="flex:1;min-width:160px"><button class="b sm" type="submit">Comment</button></form></div>` : ""}</article>`; }).join("");
  const tabs = `<nav class="fd-tabs" aria-label="Feed sections">${FEED_TABS.map(([k, label]) => `<a href="#" data-go="${feedUrl(k)}"${k === tab ? " aria-current=page" : ""}>${label}</a>`).join("")}</nav>`;
  return `<div class="fd">${tabs}<div class="fd-grid"><div class="fd-main">${note}${lead}${items || empty}</div>${feedRail()}</div></div>`;
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
<label class="toggle"><input type="checkbox" name="visible" value="1"${p.visible || (p.setup_step || 0) < 3 ? " checked" : ""}><span><b>Let approved employers find me.</b> Your profile appears in the student directory and in employers' ranked matches for their listings, with your fit score. Only employers our reviewers approved can see it.</span></label>
<label class="toggle"><input type="checkbox" name="share_resume" value="1"${p.share_resume ? " checked" : ""}><span><b>Share my resume with approved employers</b> who can see my profile.</span></label>
<label class="toggle"><input type="checkbox" name="allow_messages" value="1"${p.allow_messages !== false ? " checked" : ""}><span><b>Allow approved employers to message me.</b> Every message is scanned for scam signs, and you can block anyone.</span></label>
<label class="toggle"><input type="checkbox" name="allow_connections" value="1"${p.allow_connections !== false ? " checked" : ""}><span><b>Let other students connect with me.</b> You show up in "People you may know" and can get connection requests. Nobody can message you through the network.</span></label>
<div class="row"><a class="b sec" href="#" data-go="setup?step=2">Back</a><button class="submit-btn" type="submit">Finish</button></div></form></div>`;
  }
  const p = EP(me().id) || (S.employers[me().id] = {status: "draft"}), bar = stepsBar(step, ["Company", "Contact & FSU connection"]);
  if (step === 1) return `<div style="max-width:680px">${err}${bar}${pageHead("Tell students who you are", "A person reviews every employer before they can message students or post to the FSU feed. Clear, checkable details get approved fastest.")}
<form id="esetup1" class="card"><div class="form-field"><label for="e-co">Organization name</label><input id="e-co" name="company" required maxlength="120" value="${esc(p.company)}" placeholder="Acme Analytics"></div>
<div class="form-field"><label for="e-web">Website</label><p class="hint">Reviewers check that it matches the email you signed up with.</p><input id="e-web" name="website" required maxlength="300" value="${esc(p.website)}" placeholder="https://acme.com"></div>
<div class="grid2"><div class="form-field"><label for="e-ind">Industry</label><select id="e-ind" name="industry">${opts(INDUSTRIES, p.industry)}</select></div><div class="form-field"><label for="e-size">Size</label><select id="e-size" name="size">${opts(SIZES, p.size)}</select></div></div>
<div class="form-field"><label for="e-tag">Tagline (optional)</label><p class="hint">One line students see under your name.</p><input id="e-tag" name="tagline" maxlength="120" value="${esc(p.tagline)}" placeholder="Dashboards for Florida nonprofits and city agencies"></div>
<div class="grid2"><div class="form-field"><label for="e-loc">Location</label><input id="e-loc" name="location" maxlength="120" value="${esc(p.location)}" placeholder="Tallahassee, FL"></div>
<div class="form-field"><label for="e-founded">Founded (optional)</label><input id="e-founded" name="founded" maxlength="4" inputmode="numeric" value="${esc(p.founded)}" placeholder="2015"></div></div>
<div class="form-field"><label for="e-li">LinkedIn page (optional)</label><p class="hint">Helps students and reviewers check you out, and raises your trust score.</p><input id="e-li" name="linkedin" maxlength="300" value="${esc(p.linkedin)}" placeholder="linkedin.com/company/acme"></div>
<div class="form-field"><label for="e-about">About</label><p class="hint">What you do, in plain words. At least a couple of sentences.</p><textarea id="e-about" name="about" required maxlength="1500">${esc(p.about)}</textarea></div><button class="submit-btn" type="submit">Continue</button></form></div>`;
  return `<div style="max-width:680px">${err}${bar}${pageHead("Contact and FSU connection", "Students see who they're talking to. Reviewers use your FSU connection to approve feed access.")}
<form id="esetup2" class="card"><div class="grid2"><div class="form-field"><label for="e-cn">Your name</label><input id="e-cn" name="contact_name" required maxlength="80" value="${esc(p.contact_name)}"></div><div class="form-field"><label for="e-ct">Your title</label><input id="e-ct" name="contact_title" required maxlength="80" value="${esc(p.contact_title)}" placeholder="Campus Recruiter"></div></div>
<div class="form-field"><label for="e-fsu">How do you work with FSU students?</label><p class="hint">Internships, part-time roles, career fair, alumni, Tallahassee office. Your feed posts must be opportunities or advice for FSU students.</p><textarea id="e-fsu" name="fsu_connection" required maxlength="800" style="min-height:100px">${esc(p.fsu_connection)}</textarea></div>
<div class="form-field"><label>Kinds of roles you hire students for</label>${checks("hires_for", N.CATEGORIES.slice(0, -1), p.hires_for)}</div>
<div class="form-field"><label>Perks for student hires</label>${checks("perks", PERKS, p.perks)}</div>
<div class="row"><a class="b sec" href="#" data-go="setup?step=1">Back</a><button class="submit-btn" type="submit">${["pending", "approved"].includes(p.status) ? "Save" : "Send for review"}</button></div></form></div>`;
};
// ---------------- employer trust score + company page, same as employer_page.py ----------------
const PERKS = ["Paid", "Flexible hours", "Remote-friendly", "Mentorship", "Return offers", "Housing help", "Tuition help", "Networking events"];
const PROFILE_FIELDS = N.PROFILE_FIELDS;
function domainMatch(email, site) {
  const ed = (email || "").split("@").pop().toLowerCase(), host = ((/^https?:\/\/([^\/?#:]+)/i.exec(site || "") || [])[1] || "").toLowerCase().replace(/^www\./, "");
  if (N.FREE_MAIL.has(ed)) return "free";
  return host && (ed === host || ed.endsWith("." + host) || host.endsWith("." + ed)) ? "match" : "other";
}
function trustSignals(uid) {
  const p = EP(uid) || {}, u = U(uid) || {email: ""};
  const decided = S.jobs.filter(j => j.employer_id === uid && ["approved", "rejected", "removed"].includes(j.review_status));
  const sent = S.convos.flatMap(c => c.messages.filter(m => m.from === uid));
  const threads = S.convos.filter(c => c.employer === uid && c.messages.length && c.messages[0].from === c.student);
  let replied = 0; const hours = [];
  for (const c of threads) {
    const ms = c.messages.filter(m => m.status === "delivered"), first = ms.find(m => m.from !== uid), rep = first && ms.find(m => m.from === uid && m.at >= first.at);
    if (rep) { replied++; hours.push((rep.at - first.at) / 3600e3); }
  }
  const profile = {}; PROFILE_FIELDS.forEach(([k]) => { profile[k] = p[k]; });
  return {status: p.status || "draft", domain: domainMatch(u.email, p.website), days_approved: p.status === "approved" && p.approved_at ? (NOW() - p.approved_at) / 86400e3 : 0,
    listings: decided.length, approved: decided.filter(j => j.review_status === "approved").length, clear: decided.filter(j => j.scam_status === "clear").length,
    scam_rejections: decided.filter(j => j.review_label === "scam").length, leadgen_rejections: decided.filter(j => j.review_label === "lead_gen").length,
    sent: sent.length, held: sent.filter(m => m.status === "held" || m.band === "block").length, flagged: sent.filter(m => m.band === "review" && m.status === "delivered").length, cautioned: sent.filter(m => m.band === "caution" && m.status === "delivered").length,
    reports: S.reports.filter(r => r.employer === uid && !r.resolved).length, blocks: S.convos.filter(c => c.employer === uid && c.blocked_by === c.student).length,
    threads: threads.length, replied, reply_hours: hours.sort((a, b) => a - b), profile};
}
const trustOf = uid => N.trustFromSignals(trustSignals(uid));
const median = N.median, replyTime = N.replyTime;
const trustPill = (t, go) => { const pill = `<span class="pill ${t.tone}" title="Employer trust score: 100 is the most trustworthy">Trust ${t.score} · ${esc(t.label)}</span>`; return go ? `<a href="#" data-go="${go}" style="text-decoration:none">${pill}</a>` : pill; };
function trustCard(t, owner) {
  return `<section class="card" id="trust"><div class="phead"><h2>Trust score</h2></div><div class="fit" style="grid-template-columns:auto minmax(0,1fr)"><div class="ring sm" style="--p:${t.score}"><b>${t.score}</b></div><div><div class="fitlabel" style="font-size:19px">${esc(t.label)}</div><p class="small muted">Out of 100. Higher is safer.</p></div></div>
${t.new ? '<p class="small muted" style="margin-top:6px">New on NoleCareerShield, so part of this score is a neutral starting point.</p>' : ""}<div class="fitparts tparts">${t.parts.map(p => `<div class="cat"><span>${esc(p.name)}</span><div class="meter${p.score >= 75 ? " ok" : p.score < 45 ? " warn" : ""}"><i style="width:${p.score}%"></i></div><span>${p.score}</span><div class="why2">${esc(p.detail)}</div></div>`).join("")}</div>
<p class="small faint" style="margin-top:10px">Worked out from what this site can check: reviewer approval, email and website, how their listings were reviewed, scanner flags and reports on their messages, and how they answer students. It isn't a guarantee; still verify an employer yourself.</p>
${owner && t.tips.length ? `<h4 class="small" style="margin:14px 0 6px">Raise your score</h4><ul class="small" style="margin:0 0 0 18px">${t.tips.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}</section>`;
}
function companyHtml(p, uid, notice) {
  const owner = me().id === uid, s = trustSignals(uid), t = N.trustFromSignals(s), med = median(s.reply_hours);
  const jobs = approvedJobs().filter(j => j.employer_id === uid).slice().reverse();
  const statusPill = {approved: '<span class="pill ok">✓ Approved employer</span>', pending: '<span class="pill warn">Waiting for review</span>', rejected: '<span class="pill bad">Not approved</span>', suspended: '<span class="pill bad">Suspended</span>', draft: '<span class="pill">Profile not finished</span>'}[p.status || "draft"] || "";
  const meta = [p.industry, p.size && p.size + " people", p.location, p.founded && "Founded " + p.founded].filter(Boolean).map(esc).join(" · ");
  const links = [["website", "Website"], ["linkedin", "LinkedIn"]].filter(([k]) => p[k]).map(([k, l]) => `<a href="${esc(p[k])}" target="_blank" rel="noopener noreferrer nofollow">${l} ↗</a>`).join("");
  const actions = owner ? '<div class="row"><a class="b sm sec" href="#" data-go="setup?step=1">Edit profile</a><a class="b sm ghost" href="#" data-go="hiring">Your listings</a></div>'
    : isStudent() && p.status === "approved" ? `<div class="row"><a class="b sm" href="#" data-go="newmsg?to=${uid}">${icon("chat", 14)} Message</a>${followButton(uid, isFollowing(me().id, uid), "company?id=" + uid)}</div>` : "";
  const hero = `<section class="card phero"><div class="pbanner emp ph" aria-hidden="true" style="--ph:url(${MEDIA("arch-060.webp")})"></div><div class="pinfo"><span class="avatar xl emp">${initials(p.company)}</span>
<div class="row between" style="align-items:flex-end;gap:14px"><div style="min-width:0"><h1>${esc(p.company || "Your organization")}</h1>${p.tagline ? `<p class="headline">${esc(p.tagline)}</p>` : ""}<p class="school">${meta}</p><p class="where"><span class="plinks">${links}</span></p>
<div class="row" style="margin-top:10px">${statusPill}${trustPill(t, (owner ? "profile" : "company?id=" + uid) + "#trust")}${p.status === "approved" ? `<span class="pill">${plural(followerCount(uid), "follower")}</span>` : ""}</div></div>${actions}</div></div></section>`;
  const since = p.status === "approved" ? (s.days_approved < 30 ? "New" : `${Math.floor(s.days_approved / 30)} month${s.days_approved >= 60 ? "s" : ""}`) : "Not yet approved";
  const glance = `<section class="card"><div class="phead"><h2>Hiring at a glance</h2></div><div class="stats sm two"><div class="stat"><div class="n">${jobs.length}</div><div class="l">open listings</div></div><div class="stat"><div class="n">${s.listings}</div><div class="l">listings reviewed</div></div>
<div class="stat"><div class="n">${s.threads ? Math.round(100 * s.replied / s.threads) + "%" : "—"}</div><div class="l">student messages answered</div></div><div class="stat"><div class="n" style="font-size:17px">${esc(replyTime(med) || "—")}</div><div class="l">typical reply time</div></div></div>
<p class="small muted" style="margin-top:10px">On NoleCareerShield: ${esc(since)}</p></section>`;
  const contact = p.contact_name ? `<section class="card"><div class="phead"><h2>Contact</h2></div><div class="person"><span class="avatar emp">${initials(p.contact_name)}</span><div style="min-width:0"><div class="nm">${esc(p.contact_name)}</div><div class="sub">${esc(p.contact_title || "")}</div></div></div></section>` : "";
  const sec = (title, inner) => `<section class="card pcard"><div class="phead"><h2>${title}</h2></div>${inner}</section>`;
  const main = (p.about ? sec("About", `<p class="desc">${esc(p.about)}</p>`) : "") + (p.fsu_connection ? sec("Working with FSU students", `<p class="desc">${esc(p.fsu_connection)}</p>`) : "")
    + ((p.hires_for || []).length ? sec("Hires for", `<div class="chips">${p.hires_for.map(x => `<span class="pill">${esc(x)}</span>`).join("")}</div>`) : "")
    + ((p.perks || []).length ? sec("Perks for student hires", `<div class="chips">${p.perks.map(x => `<span class="chip">✓ ${esc(x)}</span>`).join("")}</div>`) : "")
    + `<section class="card pcard"><div class="phead"><h2>Open listings</h2><span class="small faint">${jobs.length}</span></div>${jobs.map(j => `<a class="job" href="#" data-go="job?id=${j.id}"><div class="job-title">${esc(j.title)}</div><div class="job-meta"><span class="chip">${esc(j.category)}</span><span class="chip">${esc(cap(j.work_type))}</span>${j.location ? `<span class="chip">${esc(j.location)}</span>` : ""}</div></a>`).join("") || '<p class="small muted">No open listings right now.</p>'}</section>`;
  return (notice || "") + hero + `<div class="pgrid"><aside class="pside">${trustCard(t, owner)}${glance}${contact}</aside><div class="pmain">${main}</div></div>`;
}

P.profile = () => {
  if (!me()) return needLogin("your profile");
  const data = `<h3 class="sec">Your data</h3><div class="card"><div class="row between"><div><b>Download your data</b><p class="small muted">On the live site: everything stored about your account, as a JSON file.</p></div><button class="b sm sec" type="button" data-do="export">Show my data</button></div>${S.showExport ? `<pre style="margin-top:12px;white-space:pre-wrap;font:12px/1.5 var(--mono);background:var(--sunk);padding:10px;border-radius:8px;max-height:260px;overflow:auto">${esc(exportData())}</pre>` : ""}</div>
<details class="card" style="margin-top:12px"><summary style="cursor:pointer;font-weight:600;color:var(--bad)">Delete my account</summary><p class="small muted" style="margin:8px 0 12px">Deletes your profile, resume versions, feed posts and comments, and blanks the messages you sent. This can't be undone.</p>
<form id="deleteForm"><div class="form-field"><label for="d-pw">Your password</label><input id="d-pw" type="password" name="password" required maxlength="128" autocomplete="current-password"></div><button class="b danger" type="submit">Delete my account</button></form></details>`;
  if (isStudent()) {
    const p = SP(me().id); if (!p || !p.display_name) { go("setup?step=1"); return null; }
    const notice = takeFlash() + (S.profileNotice ? banner("info", S.profileNotice) : ""); S.profileNotice = "";
    return profileHtml(p, {owner: true, showLinks: true, notice, completion: completion(p)}) + connSection(me().id, me().id) + `<div class="pdata">${data}</div>`;
  }
  const p = EP(me().id); if (!p || !p.company) { go("setup?step=1"); return null; }
  return takeFlash() + (p.status === "pending" ? banner("info", "A reviewer checks every organization, usually within a business day. In the demo, open the reviewer view to approve it.") : "") + companyHtml(p, me().id, "") + `<div class="pdata">${data}</div>`;
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
  const hero = `<section class="card phero"><div class="pbanner ph" aria-hidden="true" style="--ph:url(${MEDIA("arch-074.webp")})"></div><div class="pinfo"><span class="avatar xl">${initials(name)}</span>
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
<form id="jobVersionForm" data-job="${job.id}" data-name="${esc(("For " + job.title + " at " + job.company).slice(0, 80))}" style="margin-top:16px"><details><summary class="small" style="cursor:pointer;color:var(--accent-ink);font-weight:600">Preview and edit the tailored copy</summary>
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
const SOURCES = {applied: ["Applied", "ok"], messaged: ["Messaged you", "accent"], invited: ["You invited", "gold"], saved: ["Saved from matches", ""]};
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
const statTile = (n, l, s, of) => `<div class="stat"><div class="n">${n}</div><div class="l">${esc(l)}</div>${s ? `<div class="s">${esc(s)}</div>` : ""}${of === undefined ? "" : `<span class="fb"${of ? ` style="--f:${Math.min(1, n / of).toFixed(3)}"` : ""}><i></i></span>`}</div>`;
// Every number measured against the students who viewed: a funnel (twin of hiring._funnel).
const funnel = (s, subs, cls) => { subs = subs || ["", "", "", ""]; return `<div class="stats funnel ${cls || ""}">${statTile(s.views, "students viewed", subs[0], s.views)}${statTile(s.clicks, "clicked Apply", subs[1], s.views)}${statTile(s.messaged, "messaged you", subs[2], s.views)}${statTile(s.candidates, "candidates", subs[3], s.views)}</div>`; };
const pipeline = cands => `<div class="pipe" aria-label="Candidates by stage">${STAGES.map(([k, v]) => { const n = cands.filter(c => c.stage === k).length; return `<div class="pstep${n ? " has" : ""}"><span class="n">${n}</span><span class="l">${esc(v)}</span></div>`; }).join("")}</div>`;
function evidence(f) {
  const bits = f.matched.slice(0, 3).map(m => `<b>${esc(m.skill)}</b> <span class="faint">(${esc(m.where[0].replace("Your skills list", "skills list").replace("Your resume", "resume").replace("Your headline and about", "about"))})</span>`);
  const met = f.checklist.filter(c => c.status === "met").length;
  if (f.checklist.length) bits.push(`<span class="faint">${met} of ${f.checklist.length} requirements met</span>`);
  return bits.join(" · ");
}
function reqsHtml(f) {   // which of the listing's requirements this student meets, item by item (twin of hiring._reqs)
  if (!f.checklist.length) return "";
  const mark = {met: ["✓", "met", "Met"], missing: ["⊘", "miss", "Not met"], unknown: ["?", "unk", "Not on profile"]};
  const rows = f.checklist.map(c => `<li class="rq ${mark[c.status][1]}"><span aria-hidden="true">${mark[c.status][0]}</span><span class="sr">${mark[c.status][2]}: </span>${esc(c.text.replace(" (preferred)", ""))}`
    + `${c.must ? "<em>Required</em>" : (c.text.includes("(preferred)") ? '<em class="p">Preferred</em>' : "")}</li>`).join("");
  return `<details class="rqs"><summary>Meets ${f.met} of ${f.total} of your requirements</summary><ul>${rows}</ul></details>`;
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
${funnel(s, null, "sm")}</a>`; }).join("");
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
        ms.map(([f, p, id]) => `<div class="card mcard"><div class="row between" style="align-items:flex-start;gap:12px"><div class="row" style="gap:12px;align-items:center;min-width:0"><div class="ring sm" style="--p:${f.score}"><b>${f.score}%</b></div>${person(id)}</div><span class="pill ${f.score >= 65 ? "ok" : f.score < 45 ? "warn" : ""}">${f.percent}% match</span></div>
${p.headline ? `<p style="margin-top:8px">${esc(p.headline)}</p>` : ""}<p class="small" style="margin-top:8px">${evidence(f)}</p>${reqsHtml(f)}<div class="chips" style="margin-top:8px">${f.parts.map(x => `<span class="chip" title="${esc(x.detail)}">${esc(x.name)} ${x.score}</span>`).join("")}</div>
<div class="row" style="margin-top:12px">${live && p.allow_messages ? `<a class="b sm" href="#" data-go="newmsg?to=${id}&amp;job=${j.id}&amp;invite=1">${icon("chat", 14)} Invite to apply</a>` : ""}${saved.has(id) ? '<span class="pill ok">In candidates</span>' : `<button class="b sm sec" type="button" data-do="save-cand" data-id="${id}">Save to candidates</button>`}<a class="b sm ghost" href="#" data-go="u?id=${id}">View profile</a></div></div>`).join("")
      : '<div class="empty">No students match yet. Matches come from students who made their profile visible to approved employers.</div>');
  } else content = cands.length ? pipeline(cands) + '<p class="small muted" style="margin-bottom:12px">Stages and notes are private to your organization.</p>' + cands.map(c => {
      const p = SP(c.student); if (!p) return "";
      const f = N.fitScore(j, p), [src, st] = SOURCES[c.source] || [c.source, ""], convo = S.convos.find(x => x.student === c.student && x.employer === me().id);
      const app = S.apps.find(a => a.job === j.id && a.student === c.student);
      const msg = convo ? `<a class="b sm ghost" href="#" data-go="messages?c=${convo.id}">Open conversation</a>` : live && p.allow_messages ? `<a class="b sm ghost" href="#" data-go="newmsg?to=${c.student}&amp;job=${j.id}${c.source === "applied" ? "" : "&amp;invite=1"}">${c.source === "applied" ? "Message" : "Invite to apply"}</a>` : "";
      return `<div class="card mcard" id="c${c.student}"><div class="row between" style="align-items:flex-start;gap:12px"><div class="row" style="gap:12px;align-items:center;min-width:0"><div class="ring sm" style="--p:${f.score}"><b>${f.score}%</b></div>${person(c.student)}</div><div class="row"><span class="pill ${st}">${esc(src)}</span><span class="small faint">${ago(c.at)}</span></div></div>
<p class="small" style="margin-top:8px">${evidence(f)}</p>${reqsHtml(f)}${app ? applicationHtml(app, p) : ""}<form class="cform stageForm" data-student="${c.student}"><div class="form-field"><label for="st${c.student}">Stage</label><select id="st${c.student}" name="stage">${STAGES.map(([k, v]) => `<option value="${k}"${k === c.stage ? " selected" : ""}>${esc(v)}</option>`).join("")}</select></div>
<div class="form-field"><label for="nt${c.student}">Private note</label><input id="nt${c.student}" name="note" maxlength="300" value="${esc(c.note)}" placeholder="Only your team sees this"></div><button class="b sm" type="submit">Update</button></form>
<div class="row" style="margin-top:8px">${msg}<a class="b sm ghost" href="#" data-go="u?id=${c.student}">View profile</a></div></div>`; }).join("")
    : '<div class="empty">No candidates yet. Students appear here when they apply here, when they message you about this listing, when you invite them, or when you save them from the ranked matches.</div>';
  return `<a class="back" href="#" data-go="hiring">← Your listings</a>${takeFlash()}<div class="row between" style="align-items:flex-start;margin-top:6px"><div><h2 class="page" style="margin:0">${esc(j.title)}</h2><p class="job-co">${esc(j.company)} · ${esc(cap(j.work_type))}${j.location ? " · " + esc(j.location) : ""}</p></div><div class="row"><span class="pill ${tone}">${esc(label)}</span>${live ? `<a class="b sm sec" href="#" data-go="job?id=${j.id}">View listing</a>` : ""}</div></div>
${funnel(s, ["", s.views ? Math.round(100 * s.clicks / s.views) + "% of viewers" : "", "", stageBits])}
<p class="small faint">Views and Apply clicks are totals. You see who a student is only when they message you, you invite them, or you save them from matches.</p>
<div class="seg" role="tablist" style="margin:18px 0"><a href="#" data-go="hjob?id=${j.id}&amp;tab=matches"${tab === "matches" ? ' class="on" aria-current="page"' : ""}>Ranked matches</a><a href="#" data-go="hjob?id=${j.id}&amp;tab=candidates"${tab === "candidates" ? ' class="on" aria-current="page"' : ""}>Candidates (${cands.length})</a></div>${content}`;
};

function exportData() {
  const u = me(), d = {account: {email: u.email, role: u.role}, student_profile: SP(u.id) || null, employer_profile: EP(u.id) || null,
    messages_sent: S.convos.flatMap(c => c.messages.filter(m => m.from === u.id).map(m => ({conversation: c.id, body: m.body, status: m.status}))),
    feed_posts: S.posts.filter(p => p.author === u.id).map(p => ({kind: p.kind, body: p.body, status: p.status})), resume_versions: S.versions.filter(v => v.user === u.id).map(v => v.name),
    applications: S.apps.filter(a => a.student === u.id).map(a => ({job_id: a.job, answers: a.answers, note: a.note, share_resume: a.share ? 1 : 0, created_at: new Date(a.at).toISOString()})),
    connections: S.conns.filter(c => c.a === u.id || c.b === u.id).map(c => ({user_a: c.a, user_b: c.b, requested_by: c.by, status: c.status, created_at: new Date(c.at).toISOString()})),
    saved_posts: S.saves.filter(x => x.user === u.id).map(x => ({post_id: x.post, created_at: new Date(x.at).toISOString()})),
    assistant_chats: csChats().map(c => ({id: c.id, title: c.title, messages: c.msgs.map(m => ({role: m.role, text: m.text, feedback: m.feedback || 0}))})),
    saved_jobs: S.savedJobs.filter(x => x.user === u.id).map(x => ({job_id: x.job, created_at: new Date(x.at).toISOString()})),
    follows: S.follows.filter(f => f.student === u.id).map(f => ({employer_id: f.employer, created_at: new Date(f.at).toISOString()})),
    emails: myEmails().slice().reverse().map(m => ({subject: m.subject, body: emailBody(m), sent_at: new Date(m.at).toISOString(), read_at: m.read ? "yes" : null}))};
  return JSON.stringify(d, (k, v) => v instanceof Set ? [...v] : v, 2);
}
function canView(viewer, sid) {
  if (viewer.id === sid) return [true, true, true];
  const p = SP(sid); if (!studentReady(p)) return [false, false, false];
  if (viewer.role === "student") return [true, false, false];
  if (!approvedEmp(viewer.id)) return [false, false, false];
  const talking = S.convos.some(c => c.student === sid && c.employer === viewer.id && !c.blocked_by);
  const applied = S.apps.filter(a => a.student === sid && a.employer === viewer.id).sort((x, y) => y.at - x.at)[0];   // they chose to apply to this employer
  return p.visible || talking || applied ? [true, true, !!(p.share_resume || (applied && applied.share))] : [false, false, false];
}
P.u = () => {
  if (!me()) return needLogin("profiles");
  const id = Number(S.route.q.id), [basics, links, resume] = canView(me(), id);
  if (!basics) return '<p class="empty" style="margin:40px 0">That profile isn\'t available.</p>';
  const p = SP(id), owner = id === me().id;
  const msg = isEmployer() && p.allow_messages ? `<a class="b sm" href="#" data-go="newmsg?to=${id}">${icon("chat", 16)} Message</a>` : isStudent() && !owner ? netStrip(me().id, id, "u?id=" + id) : "";
  // Other students see the basics only; approved employers also see experience, education and projects (like Handshake).
  return `<a class="back" href="#" data-go="${isEmployer() ? "talent" : "feed"}">← Back</a>` + takeFlash() + profileHtml(p, {owner, showLinks: links, showResume: resume, messageBtn: msg, showSections: owner || isEmployer()}) + connSection(id, me().id);
};
P.company = () => {
  if (!me()) return needLogin("company pages");
  const id = Number(S.route.q.id), p = EP(id);
  if (!p || (p.status !== "approved" && id !== me().id)) return '<p class="empty" style="margin:40px 0">That organization isn\'t available.</p>';
  return '<a class="back" href="#" data-go="jobs">← Jobs</a>' + companyHtml(p, id);
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
  return pageHead("Log in to use " + what) + `<div class="row"><a class="b" href="#" data-go="${role === "employer" ? "login?role=employer" : "start"}">Log in or sign up</a>${role === "employer" ? '<a class="b sec" href="#" data-do="as-employer">Explore as a sample employer</a>' : ""}</div>`;
}
function needStudent(what) {
  if (!me()) return needLogin(what);
  return pageHead("That page is for FSU students") + banner("info", `Students use ${what}. Log out and sign in with an @fsu.edu address (the sample student is jordan@fsu.edu) to try it.`) + '<button class="b" type="button" data-do="logout">Log out</button>';
}

// ---- trust pages ----
P.employers = () => {
  if (isEmployer()) { go("hiring"); return null; }
  const hero = NCS_BLOCKS.empHero + NCS_BLOCKS.empGets + NCS_BLOCKS.howEmployers + NCS_BLOCKS.empCh;
  return {wide: true, hero, body: `<section class="home-list"><div class="card rv" style="margin:28px 0 40px"><h3 class="sec" style="margin-top:0">What students see about you</h3><p>Your company page shows your details, open listings and a trust score from 0 to 100 built from what we can check: reviewer approval, your email domain and website, how your listings were reviewed, how you answer students, and how complete your profile is. <a href="#" data-go="privacy">How we handle data</a>.</p>
<p style="margin-top:12px"><a href="#" data-go="post" style="color:var(--accent-ink);font-weight:600;text-decoration:none">Or write your first listing now and sign up when you send it →</a></p></div></section>`};
};
P.about = () => `${pageHead("About NoleCareerShield")}<div class="prose"><p>Students get targeted by fake job offers constantly: check-cashing schemes, money-mule "recruiters", and pay-to-work training programs. NoleCareerShield is a job board built around one question: <b>is this safe to respond to?</b></p>
<h3>How a listing gets on the board</h3><ul><li>Every submission is scored by an open, rule-based scam detector. Each rule that fires is explained in plain language, so the score is never a black box.</li><li>Every submission then waits for a human reviewer. Nothing is published automatically, no matter how clean the score.</li><li>Approved listings show their verdict. Listings that tripped signals are labeled and explain why.</li></ul>
<h3>Beyond the board</h3><ul><li><b>Profiles</b> that students control, including whether approved employers can find them.</li><li><b>Messaging</b> between students and reviewed employers, with every message scanned for scam signs.</li><li><b>Quick apply</b> on listings that choose it: a short form filled from your profile, sent only to that employer.</li><li><b>A network</b> where students connect with each other and follow the companies they like, with no student-to-student inbox.</li><li><b>A job assistant</b> that answers in plain words and only suggests listings that passed review.</li><li><b>A resume studio</b> that scores a resume, rewrites weak lines without inventing anything, and tailors it to a job.</li><li><b>A scam checker</b> for any message a student receives, here or anywhere else.</li><li><b>An FSU-only feed</b> where employer posts must be opportunities or advice for FSU students.</li></ul>
<h3>What this is not</h3><p>A verified badge is not a guarantee. Always confirm an employer through their own website before sharing personal information. This is an independent student project and is not affiliated with Florida State University.</p></div>`;
P.privacy = () => `${pageHead("Privacy")}<div class="prose"><p>Short version: browsing is anonymous, you choose what goes on your profile and who sees it, and you can download or delete everything at any time.</p>
<h3>Anyone browsing</h3><ul><li>Job listings are for signed-in FSU students and employers. Visitors see only a few titles on the home page.</li><li>Anyone can use the scam checker without an account, up to 10 checks a day. Visitors see the verdict and the main reasons; signed-in FSU students see every signal and the exact words it caught.</li><li>If you tell us which school you'd like NoleCareerShield at, we store only the school name.</li></ul>
<h3>Students</h3><ul><li>A student account needs a confirmed @fsu.edu address and a password, stored as a salted hash. No student ID, date of birth or SSN.</li><li>Your profile holds only what you type in. Your resume is private unless you share it with approved employers.</li><li>Employers see your profile only if a reviewer approved them and you chose to be visible or are already talking with them. They see your experience, education and projects; other students see only your name, school, headline and skills.</li><li>If you upload a resume, we can fill your profile sections from it. Nothing is added that isn't in your resume, and you can edit or delete every entry.</li><li>Your fit score for a job is worked out when you open it. If you're visible to approved employers, they can see how well you fit their listings: the same score and evidence you see.</li><li>We count which listings students open and whether they press Apply, so employers see totals. They never see who viewed or clicked.</li><li>If you message an employer about a listing, or they invite you or save you from their matches, you appear in that employer's candidate list for it, where they can add a stage and a private note.</li>
<li><b>Quick apply.</b> When you apply on a listing that collects applications here, that employer (and only that employer) sees your name, major, graduation term, profile links, your answers and note, and your resume only if you tick it. Never your email. Applying also lets that employer open your profile and message you. You can withdraw an application any time, which deletes the answers.</li>
<li><b>Connections and follows.</b> A connection is a mutual link between two students that shows as a count and as mutual connections on profiles. It doesn't let anyone message you. You can switch off connection requests and "People you may know" in your profile settings. Following a company adds its listings to a filter for you; the company sees how many students follow it, never who.</li></ul>
<h3>Messages and the feed</h3><ul><li>Messages are only between students and approved employers, and every one is scanned when sent. Messages that match scam-only patterns are held for a reviewer.</li><li>Email notifications never include message text.</li><li>Only signed-in FSU students and approved employers can read or post on the feed.</li></ul>
<h3>AI features</h3><ul><li>On the live site the assistant, resume tools and scam checker's second opinion can use Claude. Text is sent only when you use one of those features. This demo runs everything in your browser and sends nothing.</li></ul></div>`;
P.report = () => `${pageHead("Report a listing")}<div class="prose"><p>See something that looks like a scam? Use the Report button on any message or feed post, or email the site operator with the listing title and company. Reports are reviewed by a person.</p><p>If you already sent money or personal information, contact your bank and report it to the FTC at reportfraud.ftc.gov.</p></div>`;


// ---- sign in: one email box first, like Handshake (same as app.login_start) ----
const startShell = inner => `<div class="auth start"><div class="startmark" aria-hidden="true">${document.querySelector(".brand svg") ? document.querySelector(".brand svg").outerHTML : ""}</div>${inner}</div>`;
P.start = () => {
  const nx = okNext(S.route.q.next);
  return startShell(`<h2 class="auth-title">Log in or sign up</h2><p class="auth-sub">Students use their @fsu.edu address.</p>${nx.startsWith("job-") ? banner("info", "Log in with your FSU student account to see how to apply.") : ""}${takeFlash()}
<form id="startForm" data-next="${nx}"><div class="form-field"><input id="s-email" type="email" name="email" required maxlength="254" autocomplete="username" aria-label="Email" placeholder="Email" value="${esc(S.startEmail || "")}"></div>
<button class="submit-btn wide" type="submit">Continue with email</button></form><p class="start-foot">Hiring? <a href="#" data-go="employers">Employer log in or sign up →</a></p>
<p class="fine" style="margin-top:14px">Demo accounts: <b>jordan@fsu.edu</b> (student) and <b>pat@garnetanalytics.example</b> (employer). Any new @fsu.edu address works too.</p>`);
};
P.welcome = () => {
  const email = S.startEmail; if (!email) { go("start"); return null; }
  const nx = okNext(S.route.q.next);
  return startShell(`<h2 class="auth-title">Welcome to NoleCareerShield</h2><p class="auth-sub">Use your FSU account to log in as<br><b>${esc(email)}</b> <a href="#" data-go="start${nx ? "?next=" + nx : ""}">Edit</a></p>
<a class="submit-btn wide" href="#" data-go="ssodemo${nx ? "?next=" + nx : ""}">Continue to FSU single sign-on →</a>
<p style="margin-top:12px"><a href="#" class="linkbtn" data-go="login?role=student${nx ? "&amp;next=" + nx : ""}">Log in another way</a></p>
<p class="fine" style="margin-top:16px">You'll sign in on FSU's own page, with Duo if your account uses it. NoleCareerShield never sees your FSU password.</p>`);
};
// The demo can't send anyone to FSU, and it never imitates FSU's sign-in page. It says what would happen instead.
P.ssodemo = () => {
  const email = S.startEmail; if (!email) { go("start"); return null; }
  return startShell(`<h2 class="auth-title">Demo: FSU sign-in</h2><div class="banner info" style="text-align:left">On the live site, this step opens <b>FSU's own sign-in page</b> in this tab. You sign in there (and approve Duo), and FSU sends you back here already logged in. NoleCareerShield never sees your FSU password, and this demo never asks for it.</div>
<button class="submit-btn wide" type="button" data-do="sso-finish">Finish demo sign-in as ${esc(email)}</button><p style="margin-top:12px"><a href="#" class="linkbtn" data-go="welcome">Back</a></p>`);
};

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
// Every demo email also leaves an in-site copy (twin of emails.keep): only for a verified account with that address,
// and one-time sign-in links (confirm, reset) are replaced with a note, so the copy never holds a working credential.
const EMAIL_REDACTED = "[This one-time link was sent only to your email inbox.]";
function mail(to, subject, body, link) {
  const copy = S.users.some(u => u.verified && u.email.toLowerCase() === String(to || "").trim().toLowerCase());
  S.inbox.unshift({id: ++S.mailN, to, subject, body, link, at: NOW(), copy, read: false, gone: false});
}
function myEmails() { const u = me(); if (!u) return []; const e = u.email.toLowerCase(); return S.inbox.filter(m => m.copy && !m.gone && m.to.toLowerCase() === e); }
const emailBody = m => m.body + (m.link && /^(verify|reset)\b/.test(m.link.go) ? "\n\n" + EMAIL_REDACTED : "");
P.emails = () => {
  if (!me()) return needLogin("emails");
  const rows = myEmails(), cur = rows.find(m => m.id === S.route.q.id) || null;
  if (cur) cur.read = true;
  const head = pageHead("Emails", `A copy of every email we send to ${esc(me().email)}. One-time sign-in links stay in your real inbox only.`, "Inbox");
  if (!rows.length) return head + '<div class="card empty" style="padding:40px;text-align:center"><b>No emails yet</b><p class="small muted">When we email you about your account, listings or messages, a copy shows up here.</p></div>';
  const items = rows.map(m => `<a class="mi${cur && m.id === cur.id ? " on" : ""}${m.read ? "" : " unread"}" href="#" data-go="emails?id=${m.id}"><b>${esc(m.subject)}</b><small>${ago(m.at)}</small></a>`).join("");
  const view = cur ? `<a class="back" href="#" data-go="emails">← All emails</a><h2>${esc(cur.subject)}</h2><p class="small muted" style="margin:0">From NoleCareerShield · to ${esc(me().email)} · ${ago(cur.at)}</p>`
      + `<pre>${esc(emailBody(cur))}</pre><div style="margin-top:18px"><button class="b sm sec" type="button" data-do="email-delete" data-id="${cur.id}">Delete</button></div>`
    : '<p class="muted" style="margin:40px 0;text-align:center">Pick an email to read it.</p>';
  return `${head}<div class="mailbox${cur ? " open" : ""}"><div class="ml">${items}</div><div class="mv">${view}</div></div>`;
};
function newToken(u, purpose) { const t = "t" + (++S.tokN) + Math.random().toString(36).slice(2, 8); for (const k in S.tokens) if (S.tokens[k].uid === u.id && S.tokens[k].purpose === purpose) S.tokens[k].used = true; S.tokens[t] = {uid: u.id, purpose, used: false}; return t; }
function sendVerify(u) { mail(u.email, "Confirm your NoleCareerShield account", `Confirm your email to finish creating your ${u.role} account. The link works for 24 hours.\n\nIf you did not sign up, ignore this email and nothing will happen.`, {label: "Open confirmation link", go: "verify?t=" + newToken(u, "verify")}); }
const okNext = n => /^(?:post|jobs|job-\d+)$/.test(n || "") ? n : "";
const otherSide = role => role === "student" ? '<p class="start-foot" style="text-align:center">Hiring? <a href="#" data-go="employers">Employer log in or sign up →</a></p>'
  : '<p class="start-foot" style="text-align:center">Student? <a href="#" data-go="start">Log in with your @fsu.edu email →</a></p>';
const pwField = (id, name, label, check, forgot) => `<div class="form-field"><div class="label-row"><label for="${id}">${label}</label>${forgot ? `<a class="forgot" href="#" data-go="forgot?role=${forgot}">Forgot password?</a>` : ""}</div><div class="pwbox"><input id="${id}" type="password" name="${name}" required maxlength="128"${check ? " data-pwcheck" : ""}><button type="button" class="showpw" data-do="show">Show</button></div></div>`;
const RULES_LIST = `<ul class="rules" aria-label="Password requirements">${PW_CHECKS.map(c => `<li data-rule="${c[1]}">${c[0]}</li>`).join("")}</ul>`;
const auth = (title, inner, sub) => `<div class="auth"><h2 class="auth-title">${title}</h2>${sub ? `<p class="auth-sub">${sub}</p>` : ""}${inner}</div>`;
P.login = () => {
  const q = S.route.q, role = q.role === "employer" ? "employer" : "student", next = okNext(q.next) || (role === "employer" && S.pendingDraft ? "post" : ""), nx = next ? "&amp;next=" + next : "";
  const note = S.flash ? takeFlash() : role === "employer" && S.pendingDraft ? banner("info", "Log in or create an employer account to send your listing. It's saved and sent for review automatically once you're in.") : "";
  return auth(role === "student" ? "Student log in" : "Employer log in", `${note}<form id="loginForm" data-role="${role}" data-next="${next}">
<div class="form-field"><label for="f-email">Email</label><input id="f-email" type="email" name="email" required autocomplete="username" placeholder="${role === "student" ? "you@fsu.edu" : "you@company.com"}" value="${esc(S.startEmail || "")}"></div>${pwField("f-password", "password", "Password", false, role)}
<button class="submit-btn wide" type="submit">Log in</button></form><div class="or"><span>Or</span></div><a class="outline-btn" href="#" data-go="signup?role=${role}${nx}">Create ${role === "student" ? "a student" : "an employer"} account</a>
<p class="fine">Demo accounts: <b>jordan@fsu.edu</b> (student) and <b>pat@garnetanalytics.example</b> (employer), password <b>${PW}</b>.</p>${otherSide(role)}`);
};
P.signup = () => {
  const q = S.route.q, role = q.role === "employer" ? "employer" : "student", next = okNext(q.next) || (role === "employer" && S.pendingDraft ? "post" : ""), nx = next ? "&amp;next=" + next : "";
  return auth(role === "student" ? "Create your student account" : "Create your employer account", `${takeFlash()}<form id="signupForm" data-role="${role}" data-next="${next}">
<div class="form-field"><label for="f-email">Email</label><input id="f-email" type="email" name="email" required autocomplete="username" placeholder="${role === "student" ? "you@fsu.edu" : "you@company.com"}"></div>
${pwField("f-password", "password", "Password", true)}${RULES_LIST}${pwField("f-password2", "password2", "Confirm password")}
<button class="submit-btn wide" type="submit">Create account</button></form><div class="or"><span>Or</span></div><a class="outline-btn" href="#" data-go="login?role=${role}${nx}">I already have an account</a>${otherSide(role)}`,
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
const ADMIN_TABS = [["admin", "Listings"], ["aemployers", "Employers"], ["aposts", "Feed"], ["amessages", "Held messages"], ["areports", "Reports"], ["aschools", "School requests"]];
function adminCounts() { return {admin: S.jobs.filter(j => j.review_status === "pending").length, aemployers: Object.values(S.employers).filter(p => p.status === "pending").length,
  aposts: S.posts.filter(p => ["pending", "held"].includes(p.status)).length, amessages: S.convos.reduce((n, c) => n + c.messages.filter(m => m.status === "held").length, 0), areports: S.reports.filter(r => !r.resolved).length, aschools: new Set(S.schoolRequests.map(x => x.school.toLowerCase())).size}; }
P.aschools = () => { const m = new Map();
  for (const x of S.schoolRequests) { const k = x.school.toLowerCase(); const e = m.get(k) || {school: x.school, n: 0, last: 0}; e.n++; e.last = Math.max(e.last, x.at); m.set(k, e); }
  const rows = [...m.values()].sort((a, b) => b.n - a.n || b.last - a.last).map(e => `<tr><td><b>${esc(e.school)}</b></td><td>${e.n}</td><td class="small muted">${ago(e.last)}</td></tr>`).join("");
  return adminPage("School requests", "aschools", '<p class="lead">Schools that visitors asked for after using the public scam check. Only the school name is stored.</p>' + (rows ? `<div class="card"><table class="t"><tr><th>School</th><th>Requests</th><th>Latest</th></tr>${rows}</table></div>` : '<div class="empty">No requests yet. Run a scam check while logged out and use the form under the result.</div>')); };
function adminPage(title, active, body) {
  if (!S.admin) return `${pageHead("Reviewer sign-in", "The review queues are restricted. In this demo any password works.")}<form id="adminLogin" class="card" style="max-width:440px"><div class="form-field"><label for="a-pw">Password</label><input id="a-pw" type="password" name="password" required maxlength="200" autocomplete="off"></div><button class="submit-btn" type="submit">Sign in</button></form>`;
  const c = adminCounts(), tabs = ADMIN_TABS.concat([["live", "Live listings"]]);
  c.live = approvedJobs().length;
  const cells = tabs.map(([k, t]) => `<a href="#" data-go="${k}"${k === active ? ' class="on" aria-current="page"' : ""}><span class="n${c[k] ? "" : " zero"}">${c[k] || 0}</span><span class="l">${t}</span></a>`).join("");
  return `<section class="desk"><div class="desk-top"><div><div class="eyebrow">Reviewer</div><h1>${esc(title)}</h1></div><span class="keys"><kbd>J</kbd><kbd>K</kbd> next and previous card</span></div><nav class="qtabs" aria-label="Review queues">${cells}</nav></section>${body}<p style="margin-top:18px"><button class="linkbtn" type="button" data-do="admin-out">Sign out of the reviewer view</button></p>`;
}
const findingsHtml = fs => fs.filter(f => f.severity !== "note").map(f => `<div class="finding ${esc(f.severity)}"><b>${esc(f.title)}</b><br>${esc(f.why)}</div>`).join("");
P.admin = () => {
  const list = S.jobs.filter(j => j.review_status === "pending").slice().reverse();
  const rows = S.jobs.filter(j => ["legit", "scam", "lead_gen"].includes(j.review_label) && !j.seedApproved);
  let agree = 0, missed = 0, fa = 0; rows.forEach(j => { const flagged = j.scam_status !== "clear", bad = j.review_label !== "legit"; if (flagged === bad) agree++; else if (bad) missed++; else fa++; });
  const stats = rows.length ? `<p class="lead" style="font-size:13px">Detector vs your decisions: ${rows.length} labeled${rows.length < 10 ? " so far. Too few to judge; every decision is training data for the next rule update." : `, agreed on ${Math.round(100 * agree / rows.length)}%. Missed ${missed}; flagged ${fa} you approved.`}</p>` : "";
  return adminPage("Review queue", "admin", `${stats}<p class="lead">${plural(list.length, "submission")} waiting. The scam score is advisory; you decide what publishes.</p>` + (list.map(j => `<div class="rev-card"><div class="row between" style="align-items:flex-start"><div><div class="job-title">${esc(j.title)}</div><div class="job-co">${esc(j.company)}</div></div><span class="rev-score ${esc(j.scam_status)}">${esc(scorePill(j))}</span></div>
${riskMeter(j.score, j.scam_status, j.findings.some(f => f.rule_id === "lead_gen"))}
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
  return `<div class="rev-card"><div class="row between" style="align-items:flex-start"><div><div class="job-title">${esc(p.company)}</div><div class="job-co">${esc(u.email)} · ${esc(p.contact_name || "")}, ${esc(p.contact_title || "")}</div></div><div class="row">${domainNote(u.email, p.website)}${trustPill(trustOf(id))}</div></div>
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
  else if (out && out.wide) main.innerHTML = `<main id="main">${hero}${body}</main>${FOOTER}`;
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
  if (name !== "resume") { S.tailor = null; S.bulletOut = null; S.dismissed = {}; }
  if (name !== "item") S.itemDraft = null;
  if (name !== "easy") S.easyDraft = null;
  render();
}
const FOOTER = `<footer>Every listing is scanned for scam signals and reviewed by a human before it appears. A verified badge is not a guarantee. Always confirm an employer through their own website before sharing personal information.
<span class="tm"><a href="#" data-go="about">About</a> · <a href="#" data-go="privacy">Privacy</a> · <a href="#" data-go="report">Report a listing</a> · <a href="#" data-go="scam">Scam check</a></span>
<span class="tm">An independent student project. Not affiliated with, sponsored by, or endorsed by Florida State University; uses no university trademarks or logos.</span></footer>`;
function signIn(email, role) { S.session = findUser(email, role); S.chat = null; S.chatId = null; }
function afterLogin(next) {
  const u = me();
  if (u.role === "employer" && S.pendingDraft && submitDraft()) return go("posted");
  const n = okNext(next);
  if (u.role === "student" && !(SP(u.id) || {}).setup_step) return go("setup?step=1");
  if (u.role === "employer" && !(EP(u.id) || {}).company) return go("setup?step=1");
  if (n === "post" && u.role === "employer") return go("post");
  if (/^job-\d+$/.test(n)) return go("job?id=" + n.slice(4));
  go("home");
}
// Only the hiring organization may post its jobs: no staffing agencies, no second- or third-party recruiters (twin of app._RECRUITER).
const RECRUITER = new RegExp("\\b(on behalf of (?:our|a|my|an?) (?:valued |esteemed )?client|our client(?:'s)?|for (?:a|our) client|"
  + "staffing (?:agency|firm|company|partner)|recruit(?:ing|ment) (?:agency|firm|company|partner)|"
  + "(?:third|3rd|second|2nd)[- ]party recruit\\w*|headhunter|placement (?:agency|firm)|talent acquisition (?:agency|firm)|"
  + "we are a (?:recruit\\w*|staffing) )", "i");
const RECRUITER_MSG = "Only the company that is hiring can post its jobs here. Staffing agencies and second- or third-party recruiters can't post on behalf of a client.";
const CO_SUFFIX = /\b(inc|llc|l\.l\.c|ltd|co|corp|corporation|company|the|group|pllc|pa|plc)\b\.?/gi;
const coKey = name => String(name || "").toLowerCase().replace(CO_SUFFIX, "").replace(/[^a-z0-9]/g, "");
function companyMismatch(employerCompany, posted) {   // true when an employer tries to post for an organization other than their own
  const a = coKey(employerCompany), b = coKey(posted);
  return !!(a && b && !b.includes(a) && !a.includes(b));
}
function submitDraft() {
  const d = S.pendingDraft; S.pendingDraft = null; if (!d) return false;
  const ep = EP(me().id) || {};
  if (companyMismatch(ep.company || "", d.company)) return false;   // same as app._resume_draft: a listing for someone else's company isn't sent
  if (!d.poster_name) d.poster_name = ep.contact_name || "";   // a listing always names the person who posted it
  if (!d.poster_title) d.poster_title = ep.contact_title || "";
  delete d.direct;
  const j = Object.assign({id: S.nextJob++, employer_id: me().id, age_days: 0, review_status: "pending", review_label: null}, d);
  scoreJob(j); S.jobs.push(j);
  mail(me().email, "We received your listing", `We received your listing "${d.title}". It has been scanned, and a person reviews every listing before it appears on the board.`, null);
  return true;
}

// ---------------- events ----------------
document.addEventListener("click", e => {
  const ap = e.target.closest("[data-apply]"); if (ap && isStudent()) { const jk = Number(ap.dataset.apply); (S.clicks[jk] = S.clicks[jk] || new Set()).add(me().id);
    const had = appliedTo(jk, me().id); S.applyClicks.add(jk + ":" + me().id); if (!had) setTimeout(() => render(true), 0); return; }   // the poster's Message button appears once you applied
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
    "sso-finish": () => { // what FSU sign-in hands back: a confirmed @fsu.edu address. First time? The account is created, like the live site.
      const email = S.startEmail; let u = findUser(email, "student");
      if (!u) { u = {id: S.nextId++, email, role: "student", pw: null, verified: true}; S.users.push(u); }
      u.verified = true; S.session = u; S.chat = null; S.chatId = null; const nx = okNext(S.route.q.next); S.startEmail = ""; afterLogin(nx); },
    "as-student": () => { S.admin = false; signIn("jordan@fsu.edu", "student"); go("home"); },
    "as-employer": () => { S.admin = false; signIn("pat@garnetanalytics.example", "employer"); go("home"); },
    "as-reviewer": () => { S.admin = true; go("admin"); },
    logout: () => { S.session = null; go("home"); },
    "admin-out": () => { S.admin = false; go("home"); },
    reset: () => { S.timers.forEach(clearTimeout); reset(); render(); },
    show: () => { const i = d.parentElement.querySelector("input"); i.type = i.type === "password" ? "text" : "password"; d.textContent = i.type === "password" ? "Show" : "Hide"; },
    lsample: () => { if (!me() && (S.publicChecks = (S.publicChecks || 0) + 1) > 10) { flash("warning", "Visitors can run 10 checks a day. Log in with your @fsu.edu email for more."); return go("scam"); }
      S.listingIn = Object.assign({}, LISTING_SAMPLES[Number(d.dataset.i)][1]); go("scam?run=1"); },
    sample: () => { if (!me() && (S.publicChecks = (S.publicChecks || 0) + 1) > 10) { flash("warning", "Visitors can run 10 checks a day. Log in with your @fsu.edu email for more."); return go("scam?kind=message"); }
      const s = SAMPLES[Number(d.dataset.i)]; go(`scam?kind=message&run=1&text=${encodeURIComponent(s[1])}&sender=${encodeURIComponent(s[2])}`); },
    "cs-ask": () => ask(d.dataset.q),
    "cs-new": () => { S.chatId = null; go("assistant"); },
    "cs-open": () => { S.chatId = Number(d.dataset.id); S.scrollTo = "latest"; go("assistant"); },
    "cs-del": () => { S.chats = (S.chats || []).filter(c => !(c.id === id && c.user === me().id)); if (S.chatId === id) S.chatId = null; render(true); },
    "cs-fb": () => { const ch = csChat(S.chatId), m = ch && ch.msgs.find(x => x.id === Number(d.dataset.m)); if (m && m.role === "assistant") { const v = d.dataset.v === "up" ? 1 : -1; m.feedback = m.feedback === v ? 0 : v; render(true); } },
    "cs-copy": () => { const ch = csChat(S.chatId), m = ch && ch.msgs.find(x => x.id === Number(d.dataset.m)); if (m) { try { navigator.clipboard.writeText(m.text).then(() => { d.classList.add("on"); d.title = "Copied"; }, () => {}); } catch (x) { /* clipboard unavailable */ } } },
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
    accept: () => rsAccept(d.dataset.ctx, d.dataset.sid),
    dismiss: () => { const k = d.dataset.ctx; (S.dismissed[k] || (S.dismissed[k] = new Set())).add(d.dataset.sid); render(true); },
    undismiss: () => { delete S.dismissed[d.dataset.ctx]; render(true); },
    "del-version": () => { S.versions = S.versions.filter(x => x.id !== id); render(true); },
    block: () => { c.blocked_by = me().id; render(true); }, unblock: () => { c.blocked_by = null; render(true); },
    archive: () => { c.hidden[me().id] = true; go("messages"); },
    "report-convo": () => { const last = c.messages.filter(m => m.from !== me().id).pop(); S.reports.push({what: "Conversation reported", by: me().id, employer: isStudent() ? c.employer : null, text: last ? last.body : "(no messages)", at: NOW()}); flash("verified", "Reported. A reviewer will look at this conversation. You can also block the sender."); render(true); },
    helpful: () => { const p = S.posts.find(x => x.id === id); p.helpful.has(me().id) ? p.helpful.delete(me().id) : p.helpful.add(me().id); render(true); },
    comments: () => { S.openComments = S.openComments === id ? null : id; render(true); },
    "report-post": () => { const p = S.posts.find(x => x.id === id); if (!p.reports.has(me().id)) { p.reports.add(me().id); S.reports.push({what: "Feed post reported", by: me().id, text: p.body, at: NOW()}); if (p.reports.size >= 3) p.status = "held"; } render(true); },
    save: () => { const p = S.posts.find(x => x.id === id); if (p && p.status === "published" && !isSaved(me().id, id) && S.saves.filter(x => x.user === me().id).length < MAX_SAVES) S.saves.push({user: me().id, post: id, at: NOW()}); render(true); },
    unsave: () => { S.saves = S.saves.filter(x => !(x.user === me().id && x.post === id)); render(true); },
    "job-save": () => { const j = S.jobs.find(x => x.id === id);
      if (isStudent() && j && j.review_status === "approved" && !S.savedJobs.some(x => x.user === me().id && x.job === id) && S.savedJobs.filter(x => x.user === me().id).length < JB_MAX_SAVED) S.savedJobs.push({user: me().id, job: id, at: NOW()});
      render(true); },
    "job-unsave": () => { S.savedJobs = S.savedJobs.filter(x => !(x.user === me().id && x.job === id)); render(true); },
    "del-post": () => { S.posts = S.posts.filter(x => x.id !== id); S.saves = S.saves.filter(x => x.post !== id); render(true); },
    export: () => { S.showExport = !S.showExport; render(true); },
    "email-delete": () => { const m = myEmails().find(x => x.id === id); if (m) m.gone = true; go("emails"); },
    "emp-approve": () => { EP(id).status = "approved"; EP(id).approved_at = NOW(); mail(U(id).email, "Your organization was approved", "A reviewer approved your organization. You can now message students, browse the directory and post to the FSU feed.", null); render(true); },
    "emp-reject": () => { EP(id).status = "rejected"; EP(id).status_note = d.dataset.note; render(true); },
    "emp-suspend": () => { EP(id).status = "suspended"; S.convos.forEach(cv => cv.messages.forEach(m => { if (m.from === id && m.status === "held") m.status = "removed"; })); render(true); },
    "post-publish": () => { S.posts.find(x => x.id === id).status = "published"; render(true); },
    "post-reject": () => { S.posts.find(x => x.id === id).status = "rejected"; render(true); },
    "msg-deliver": () => { const cv = S.convos.find(x => x.id === Number(d.dataset.c)); cv.messages.find(m => m.id === id).status = "delivered"; render(true); },
    "msg-remove": () => { const cv = S.convos.find(x => x.id === Number(d.dataset.c)); cv.messages.find(m => m.id === id).status = "removed"; render(true); },
    "report-resolve": () => { S.reports[Number(d.dataset.i)].resolved = true; render(true); },
    follow: () => { if (approvedEmp(id) && isStudent() && !isFollowing(me().id, id)) S.follows.push({student: me().id, employer: id, at: NOW()}); netBack(d.dataset.next || "company?id=" + id, "followed"); },
    unfollow: () => { S.follows = S.follows.filter(f => !(f.student === me().id && f.employer === id)); netBack(d.dataset.next || "company?id=" + id, "unfollowed"); },
    "net-accept": () => netRespond(id, "accept", d.dataset.next), "net-decline": () => netRespond(id, "decline", d.dataset.next), "net-remove": () => netRemove(id, d.dataset.next),
    withdraw: () => { S.apps = S.apps.filter(a => !(a.job === id && a.student === me().id));   // still untouched in the employer's tracker? Then it goes too.
      S.candidates = S.candidates.filter(c => !(c.job === id && c.student === me().id && c.source === "applied" && c.stage === "new")); flash("info", "Application withdrawn."); render(true); },
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
  if (id === "jbSearch") { const rq = S.route.q, keep = {}; ["category", "work_type", "kind", "loc", "when", "quick", "following", "sort"].forEach(k => { if (rq[k]) keep[k] = rq[k]; }); return go(jbUrl(jbParams(Object.assign(keep, {search: g("search")}), isStudent()))); }
  if (id === "talentForm") return go("talent" + (g("q") ? "?q=" + encodeURIComponent(g("q")) : ""));
  if (id === "adminLogin") { S.admin = true; return go("admin"); }
  if (id === "scamForm") { if (!g("text")) return;
    if (!me() && (S.publicChecks = (S.publicChecks || 0) + 1) > 10) { flash("warning", "Visitors can run 10 checks a day. Log in with your @fsu.edu email for more."); return go("scam?kind=message"); }
    return go(`scam?kind=message&run=1&text=${encodeURIComponent(g("text").slice(0, 8000))}&sender=${encodeURIComponent(g("sender"))}`); }
  if (id === "listingForm") {
    const v = {}; for (const k of ["title", "company", "description", "url", "contact"]) v[k] = g(k);
    S.listingIn = v;
    if (!v.title || v.description.length < 40) { flash("warning", "Add the job title and paste the listing (at least a couple of sentences)."); return go("scam"); }
    if (v.url && !/^(?:https?:\/\/)?[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?:[\/?#:][^\s<>"']*)?$/.test(v.url)) { flash("warning", "The apply link doesn't look like a web address. Leave it empty if there isn't one."); return go("scam"); }
    if (v.url && !/^https?:\/\//i.test(v.url)) v.url = "https://" + v.url;
    if (!me() && (S.publicChecks = (S.publicChecks || 0) + 1) > 10) { flash("warning", "Visitors can run 10 checks a day. Log in with your @fsu.edu email for more."); return go("scam"); }
    return go("scam?run=1");
  }
  if (id === "schoolForm") { const name = g("school").replace(/\s+/g, " ").slice(0, 80);
    if (name.length < 3 || !/[A-Za-z]{2}/.test(name) || /[<>{}@]|https?:|www\./.test(name)) { flash("warning", "Type your school's name, like University of Florida."); return render(true); }
    S.schoolRequests.push({school: name, at: NOW()}); S.schoolDone = name; return render(true); }
  if (id === "askForm") { ask(g("q")); return; }
  if (id === "easyForm") return sendApplication(f, fd);
  if (f.classList.contains("cform2")) return netConnect(Number(f.dataset.to), g("note"), f.dataset.next);
  if (id === "startForm") {
    const email = g("email").toLowerCase(), nx = f.dataset.next;
    if (!EMAIL_RE.test(email)) { flash("warning", "Enter a valid email address."); S.startEmail = email; return go("start"); }
    S.startEmail = email;
    if (email.split("@").pop() === "fsu.edu") return go("welcome" + (nx ? "?next=" + nx : ""));
    flash("info", "That isn't an @fsu.edu address, so this is an employer login. Students: go back and use your FSU email.");
    return go("login?role=employer" + (nx ? "&next=" + nx : ""));
  }
  if (id === "loginForm") {
    const role = f.dataset.role, u = findUser(g("email").toLowerCase(), role);
    if (!u || u.pw !== fd.get("password")) { flash("warning", "The email or password is incorrect."); return go(`login?role=${role}&next=${f.dataset.next}`); }
    if (!u.verified) { flash("warning", `Confirm your email first. We sent you a link when you signed up. <button type="button" class="linkbtn" data-do="resend" data-role="${role}" data-email="${esc(u.email)}">Send me a new confirmation email</button>`, true); return go(`login?role=${role}&next=${f.dataset.next}`); }
    S.session = u; S.chat = null; S.chatId = null; return afterLogin(f.dataset.next);
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
    rec.used = true; u.verified = true; S.session = u; S.chat = null; S.chatId = null;
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
    const qt = many("qtext"), qk = many("qkind"), qr = many("qreq");
    const d = {title: g("title"), company: g("company"), category: g("category"), work_type: g("work_type"), location: g("location"), description: g("description"), apply_url: g("apply_url"), contact: "",
      easy_apply: fd.get("easy_apply") ? 1 : 0, questions: qt.slice(0, MAX_QUESTIONS).map((t, i) => ({q: t, kind: qk[i] || "short", required: qr[i] === "1"})),
      poster_name: g("poster_name").replace(/\s+/g, " ").slice(0, 80), poster_title: g("poster_title").replace(/\s+/g, " ").slice(0, 80), show_email: fd.get("show_email") ? 1 : 0, direct: fd.get("direct") ? 1 : 0};
    S.draft = d;
    // Only the hiring organization may post its jobs (twin of app._clean_listing).
    if (!d.direct) { flash("warning", "Confirm that you work directly for this company. " + RECRUITER_MSG); return render(); }
    if (RECRUITER.test([d.title, d.company, d.description, d.poster_title].join(" "))) { flash("warning", RECRUITER_MSG); return render(); }
    if (!d.title || !d.company || !d.description) { flash("warning", "Title, company and description are required."); return render(); }
    if (d.apply_url && !/^https?:\/\/[^\s<>"']+$/i.test(d.apply_url)) { flash("warning", "The apply URL must start with http:// or https://."); return render(); }
    try { d.questions = cleanQuestions(d.questions); } catch (err) { flash("warning", String(err)); S.draft.questions = qt.map((t, i) => ({q: t, kind: qk[i] || "short", required: qr[i] === "1"})); return render(); }
    S.pendingDraft = d; S.draft = null;
    if (isEmployer()) {
      const ep = EP(me().id) || {};
      if (companyMismatch(ep.company || "", d.company)) { S.draft = d; S.pendingDraft = null; flash("warning", `You can only post jobs for your own organization (${ep.company}). ` + RECRUITER_MSG); return render(); }
      submitDraft(); return go("posted"); }
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
    Object.assign(p, {links: {linkedin: li, website: web}, visible: !!fd.get("visible"), share_resume: !!fd.get("share_resume"), allow_messages: !!fd.get("allow_messages"), allow_connections: !!fd.get("allow_connections"), setup_step: 3});
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
    const founded = g("founded"), li = url(g("linkedin"), "linkedin.com");
    if (founded && !(/^(?:18|19|20)\d{2}$/.test(founded) && Number(founded) <= new Date().getFullYear())) return back(1, "Founded should be a year, like 2015.");
    if (li === null) return back(1, "LinkedIn should be a linkedin.com address.");
    Object.assign(p, {company: g("company").slice(0, 120), website: web, industry: g("industry"), size: g("size"), location: g("location").slice(0, 120), about: g("about").slice(0, 1500),
      tagline: g("tagline").slice(0, 120), founded, linkedin: li});
    return go("setup?step=2"); }
  if (id === "esetup2") { const p = EP(me().id);
    if (!g("contact_name") || !g("contact_title") || !g("fsu_connection")) return back(2, "Fill in your name, title and how you work with FSU students.");
    Object.assign(p, {contact_name: g("contact_name"), contact_title: g("contact_title"), fsu_connection: g("fsu_connection").slice(0, 800),
      hires_for: many("hires_for").filter(x => N.CATEGORIES.includes(x)), perks: many("perks").filter(x => PERKS.includes(x))});
    if (["draft", "rejected", undefined].includes(p.status)) p.status = "pending";
    return go("profile"); }
  if (id === "deleteForm") {
    if (fd.get("password") !== me().pw) { flash("warning", "That password isn't right, so nothing was deleted."); return go("profile"); }
    const uid = me().id; S.users = S.users.filter(u => u.id !== uid); delete S.students[uid]; delete S.employers[uid];
    const gone = new Set(S.posts.filter(p => p.author === uid).map(p => p.id)); S.saves = S.saves.filter(x => x.user !== uid && !gone.has(x.post));
    S.posts = S.posts.filter(p => p.author !== uid); S.posts.forEach(p => { p.comments = p.comments.filter(c => c.author !== uid); });
    S.convos.forEach(c => { c.messages.forEach(m => { if (m.from === uid) { m.body = ""; m.status = "removed"; } }); if (c.student === uid || c.employer === uid) c.blocked_by = uid; });
    S.versions = S.versions.filter(v => v.user !== uid); S.apps = S.apps.filter(a => a.student !== uid && a.employer !== uid);
    S.conns = S.conns.filter(c => c.a !== uid && c.b !== uid); S.follows = S.follows.filter(x => x.student !== uid && x.employer !== uid); S.savedJobs = S.savedJobs.filter(x => x.user !== uid); S.session = null;
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
      flash("verified", `Read ${name}.` + (n ? ` We also filled ${n} profile entr${n === 1 ? "y" : "ies"} from it; check them on your profile.` : "")); go("resume?src=main"); };
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
  if (id === "jobVersionForm") { S.versions.unshift({id: Date.now(), user: me().id, name: f.dataset.name || "Tailored copy", body: String(fd.get("body") || "").trim(), job: Number(f.dataset.job) || 0, at: NOW()});
    flash("verified", "Saved a tailored copy. Your main resume didn't change."); return go("resume?tab=versions"); }
  if (id === "resumeSave") { const t = String(fd.get("text") || ""); if (t.trim().length < 80) { flash("warning", "A resume needs 80 to 20,000 characters."); return render(); }
    SP(me().id).resume_text = t.slice(0, 20000); flash("verified", "Saved."); return render(true); }
  if (id === "bulletForm") { S.bulletIn = g("bullet"); S.bulletOut = S.bulletIn ? N.improveBullet(S.bulletIn) : null; return render(true); }
  if (id === "rsPick") return go("resume?src=" + g("src"));
  if (id === "rsJobPick") { if (!g("job")) return; return go("resume?tab=tailor&job=" + g("job")); }
  if (id === "tailorForm") {
    const jid = Number(g("job_id"));
    if (jid) { if (!approvedJobs().some(x => x.id === jid)) return; S.tailor = null; return go("resume?tab=tailor&job=" + jid); }
    const ttl = g("title") || "this job", desc = g("description");
    if (desc.length < 60) { flash("warning", "Pick a listing, or paste a job description (at least a few sentences)."); return render(); }
    S.tailor = {title: ttl, desc}; S.route.q.job = 0; return render();
  }
  if (id === "versionForm") { S.versions.unshift({id: Date.now(), user: me().id, name: g("name") || "Tailored copy", body: String(fd.get("body") || "").trim(), job: Number(g("job_id")) || 0, at: NOW()}); S.tailor = null; return go("resume?tab=versions"); }
});

reset();
render();
})();
