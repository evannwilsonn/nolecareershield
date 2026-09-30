"""Tactic-level asks (scam_detector/asks.py) and multi-message thread analysis (scam_detector/conversation.py).

Threads are written from the wording of the repo's labeled scam data (scam_detector/data) and the public
university phishing-archive patterns it came from (Cornell, Syracuse, Berkeley, UofT, QY Shippers, Indeed/TikTok
"recruiter" texts).
"""
import collections
import glob
import json
import os

import pytest

from scam_detector.asks import MONEY_ASKS, ask_ids, extract_asks
from scam_detector.conversation import SCRIPTS, STAGES, analyze_thread, split_turns, stage_of

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "scam_detector", "data")

# ---------------------------------------------------------------- threads

FAKE_CHECK_EARLY = """Prof. Daniel Reyes: Good afternoon, I got your contact from the FSU student directory. The Department of Economics urgently requires a remote research assistant, paid $350 weekly for 4 hours a week. Kindly text me at 850-555-0147 with your full name, year of study and department to proceed.

Me: Hi, I'm interested. Is there an interview?

Prof. Daniel Reyes: No interview is required, your application has been processed and you have been deemed qualified. Your first task: check online and get me the prices of an Acer TravelMate laptop and a Brother laser printer.

Me: Done, I sent you the prices.

Prof. Daniel Reyes: Looks great. Which bank do you use, and do you have mobile banking? Payroll needs it to set up your weekly pay."""

FAKE_CHECK_LATER = """

Prof. Daniel Reyes: Attached is the paycheck to cover your first weekly pay and the office supplies. Kindly make a mobile deposit today.

Me: OK, it shows as pending.

Prof. Daniel Reyes: Now make a payment worth $1,850 to our equipment vendor on Zelle right away and send me the confirmation. You'll be charged if the supplies are late."""

FAKE_CHECK = FAKE_CHECK_EARLY + FAKE_CHECK_LATER

TASK_SCAM_WHATSAPP = """10/12/26, 3:04 PM - Messages and calls are end-to-end encrypted. No one outside of this chat, not even WhatsApp, can read or listen to them. Tap to learn more.
10/12/26, 3:04 PM - Emily (Indeed): Hi! Sorry to bother you. I'm a recruiter at Indeed. We have a remote part-time role, 60-90 minutes a day, earn $200-$800 daily. No experience is required. Interested?
10/12/26, 3:06 PM - Evan: Sure, what is it?
10/12/26, 3:07 PM - Emily (Indeed): You complete product optimization tasks on our merchant platform and earn a commission on every set of tasks.
Your mentor will train you today.
10/12/26, 3:10 PM - Evan: ok
10/13/26, 9:15 AM - Emily (Indeed): Congratulations, you finished your first set! You got a combination order, so your account shows a negative balance. Recharge your account with 300 USDT to unlock your withdrawal. Complete it today or your earnings will be frozen.
10/13/26, 9:20 AM - Evan: <Media omitted>
10/13/26, 9:21 AM - Evan: I don't have that much"""

RESHIPPING_EMAIL = """From: Riley Moss <person15@qy-shippers.com>
Sent: Monday, November 30, 2026 10:39 AM
To: evan.wilson@fsu.edu
Subject: RE: WELCOME TO QY SHIPPERS

Confirm Employment Acceptance. Reply with the address to send packs, and attach a front and back photo of any government-issued identification. Once parcels are delivered to your home, take pictures, relabel them with the prepaid shipping labels we email you, and send them on to our overseas customers.

-----Original Message-----
From: Evan Wilson <evan.wilson@fsu.edu>
Sent: Saturday, November 28, 2026 9:12 AM
To: HR Department <hr@qy-shippers.com>
Subject: RE: Open vacancy at QY SHIPPERS

Hi, I'm interested in the Quality Control Inspector position. What does the job involve?

-----Original Message-----
From: Casey Dunn <person31@qy-shippers.com>
Sent: Friday, November 27, 2026 12:21 PM
To: evan.wilson@fsu.edu
Subject: Open vacancy at QY SHIPPERS

Dear Evan, we came across your CV on a job seeking resource. The Quality Control Inspector position offers a fixed monthly salary of $2,800 plus a bonus of $50 for each successful package sent. Kindly respond to this email with your full name, address, and cell phone."""

LEGIT_RECRUITER = """Hi Evan,

Thanks for confirming. Your offer letter is attached; please review and sign it in Workday by Friday. After you accept the offer, HR will send the direct deposit and W-4 forms through the onboarding portal, and your background check is paid by us. Your start date is January 12.

Best,
Maria Chen
University Recruiting | Raymond James
maria.chen@raymondjames.com

On Tue, Oct 20, 2026 at 4:10 PM Evan Wilson <evan.wilson@fsu.edu> wrote:
> Hi Maria, thank you, the interview with the team went well and I'm excited about the role. Thursday works for any follow-up.
>
> On Mon, Oct 12, 2026 at 10:02 AM Maria Chen <maria.chen@raymondjames.com> wrote:
>> Hi Evan, I'm a campus recruiter at Raymond James. I came across your profile on Handshake after the FSU career fair and wanted to invite you to interview for our Operations Analyst internship.
>> Please pick a 45-minute video interview slot with our team at raymondjames.com/careers/schedule. The role pays $22/hour. We will never ask you to pay a fee or deposit a check."""


# ---------------------------------------------------------------- full threads

def test_fake_check_thread_is_high_risk_and_predicts_the_vendor_payment():
    r = analyze_thread(FAKE_CHECK)
    assert r["risk"] == "high"
    assert r["script"] == "fake_check"
    assert r["furthest_stage"] == "pressure"
    assert r["trajectory"][:2] == ["hook", "legitimacy"]
    for st in ("channel_switch", "onboarding", "data_grab", "ask", "pressure"):
        assert st in r["trajectory"]
    ids = {f["rule_id"]: f for f in r["findings"]}
    assert ids["conversation_script"]["severity"] == "critical"
    assert "channel_switch_then_data" in ids
    asks = {a["ask"] for t in r["turns"] for a in t["asks"]}
    assert {"deposit_check", "send_money_on", "bank_details", "move_off_platform", "no_interview"} <= asks
    assert "Zelle" in r["warning"] and "Don't deposit" in r["warning"]
    assert "bouncing" in r["next_step"]
    speakers = [t["speaker"] for t in r["turns"]]
    assert speakers == ["them", "me", "them", "me", "them", "them", "me", "them"]


def test_task_scam_whatsapp_export():
    r = analyze_thread(TASK_SCAM_WHATSAPP)
    assert r["script"] == "task_scam"
    assert r["risk"] == "high"
    asks = {a["ask"] for t in r["turns"] for a in t["asks"]}
    assert {"task_deposit", "crypto"} <= asks
    assert "pressure" in r["trajectory"]
    assert any(f["rule_id"] == "conversation_script" and f["severity"] == "critical" for f in r["findings"])
    assert "combination order" in r["next_step"]     # after the ask, the prediction moves past it


def test_reshipping_email_chain_is_reordered_and_flagged():
    r = analyze_thread(RESHIPPING_EMAIL)
    assert [t["speaker"] for t in r["turns"]] == ["them", "me", "them"]
    assert r["turns"][0]["text"].startswith("Open vacancy")
    assert r["script"] == "reshipping"
    assert r["risk"] == "high"
    last = {a["ask"] for a in r["turns"][-1]["asks"]}
    assert {"reship", "identity_docs"} <= last


def test_legit_recruiter_thread_stays_low_risk():
    r = analyze_thread(LEGIT_RECRUITER)
    assert r["risk"] == "low", r
    assert r["script"] is None and r["next_step"] is None
    assert r["findings"] == []
    assert all(not t["asks"] for t in r["turns"])
    assert [t["speaker"] for t in r["turns"]] == ["them", "me", "them"]
    assert "career fair" in r["turns"][0]["text"]


def test_legit_single_posting_with_disclaimers_is_low():
    text = ("Account Coordinator. Important: we will never ask you for money, a training fee, an equipment fee, or your "
            "banking details during hiring. We do not conduct interviews on WhatsApp or Telegram. All messages come from "
            "@harborlane.com addresses. Pay is $24-$28/hr. New hires complete the I-9 and W-4 and provide their Social "
            "Security number for payroll upon hire.")
    r = analyze_thread(text)
    assert r["risk"] == "low" and r["findings"] == []


# ---------------------------------------------------------------- early warning

def test_early_warning_before_any_money_ask():
    r = analyze_thread(FAKE_CHECK_EARLY)
    assert "ask" not in r["trajectory"]
    assert r["furthest_stage"] == "data_grab"
    assert r["script"] == "fake_check"
    f = {x["rule_id"]: x for x in r["findings"]}
    assert f["conversation_script"]["severity"] == "warning"
    assert f["channel_switch_then_data"]["severity"] == "warning"
    assert r["risk"] in ("medium", "high")
    w = r["warning"]
    assert w.startswith("This follows the fake-check script")
    assert "moved you to text" in w and "skipped the interview" in w and "asked about your bank" in w
    assert "check to deposit" in w and "Don't deposit anything" in w


def test_early_warning_identity_harvest_at_onboarding():
    thread = """Recruiter: Hi, I'm a recruiter with Redfern. We came across your resume and have a remote analyst role, $45/hr, no interview required.

Me: Sounds good, what's next?

Recruiter: Great. Please reply from your personal email with your full name, mailing address, date of birth and a photo of your driver's license so HR can set up your account."""
    r = analyze_thread(thread)
    assert "ask" not in r["trajectory"]
    assert r["furthest_stage"] == "data_grab"
    assert r["script"] == "identity_harvest"
    assert any(f["rule_id"] == "conversation_script" and f["severity"] == "warning" for f in r["findings"])
    assert r["risk"] in ("medium", "high")


def test_early_warning_task_scam_before_top_up():
    thread = """Recruiter: Hello, sorry to interrupt. I'm from TikTok HR. Part-time, 30-60 minutes a day, earn $300-$900 daily. Please add our manager on WhatsApp +1 555 0100 to get the job details.

Me: ok added

Recruiter: Your mentor will train you on app store data optimization tasks today. You earn a commission on every set of tasks."""
    r = analyze_thread(thread)
    assert "ask" not in r["trajectory"]
    assert r["script"] == "task_scam"
    assert any(f["rule_id"] == "conversation_script" and f["severity"] == "warning" for f in r["findings"])
    assert "top up" in r["next_step"]


# ---------------------------------------------------------------- turn splitting

def test_split_single_message_is_one_turn():
    t = split_turns("Dear student, we got your contact through your school directory. Earn $500 weekly.")
    assert len(t) == 1 and t[0]["speaker"] == "unknown"
    assert split_turns("") == []


def test_split_speaker_labels():
    t = split_turns(FAKE_CHECK_EARLY)
    assert [x["speaker"] for x in t] == ["them", "me", "them", "me", "them"]
    assert t[1]["text"].startswith("Hi, I'm interested")


def test_form_fields_are_not_speaker_labels():
    text = "Opening: Personal Assistant\n\nStyle: Part-Time Job\n\nHrs: Average of 3-6hrs weekly\n\nPay: $670 weekly"
    assert len(split_turns(text)) == 1


def test_split_whatsapp_android_export():
    t = split_turns(TASK_SCAM_WHATSAPP)
    assert [x["who"] for x in t] == ["Emily (Indeed)", "Evan", "Emily (Indeed)", "Evan", "Emily (Indeed)", "Evan"]
    assert [x["speaker"] for x in t] == ["them", "me", "them", "me", "them", "me"]
    assert "Your mentor will train you today." in t[2]["text"]          # continuation line kept
    assert not any("end-to-end encrypted" in x["text"] for x in t)     # system line dropped
    t2 = split_turns(TASK_SCAM_WHATSAPP, me="Evan")
    assert [x["speaker"] for x in t2] == [x["speaker"] for x in t]


def test_split_whatsapp_ios_export():
    text = ("[10/12/26, 3:04:05 PM] Mia Recruiter: Hi, are you interested in a remote job? $500 weekly.\n"
            "[10/12/26, 3:05:10 PM] Evan: yes\n"
            "[10/12/26, 3:06:00 PM] Mia Recruiter: Kindly provide your full name and mailing address.")
    t = split_turns(text, me="Evan")
    assert [x["speaker"] for x in t] == ["them", "me", "them"]
    assert t[2]["text"].startswith("Kindly provide")


def test_split_bracket_timestamps():
    text = ("[9:41 AM] Recruiter: Congratulations, you have been hired. No interview is needed.\n"
            "[9:43 AM] Me: great, what now?\n"
            "[9:44 AM] Recruiter: We will mail you a check to purchase your equipment from our vendor.")
    t = split_turns(text)
    assert [x["speaker"] for x in t] == ["them", "me", "them"]
    r = analyze_thread(text)
    assert r["script"] == "fake_check" and r["risk"] == "high"


def test_split_from_header_chain_sorted_by_date():
    t = split_turns(RESHIPPING_EMAIL)
    assert [x["who"].split(" <")[0] for x in t] == ["Casey Dunn", "Evan Wilson", "Riley Moss"]
    assert "-----Original Message-----" not in "".join(x["text"] for x in t)
    t2 = split_turns(RESHIPPING_EMAIL, me="evan.wilson@fsu.edu")
    assert [x["speaker"] for x in t2] == ["them", "me", "them"]


def test_split_original_message_without_dates_is_reversed():
    text = ("Please make the mobile deposit today.\n\n"
            "-----Original Message-----\n"
            "Hi professor, I received the check.\n\n"
            "-----Original Message-----\n"
            "Attached is the paycheck to cover the expenses for the office supplies.")
    t = split_turns(text)
    assert [x["text"] for x in t] == ["Attached is the paycheck to cover the expenses for the office supplies.",
                                      "Hi professor, I received the check.", "Please make the mobile deposit today."]


def test_split_quoted_reply_chain():
    t = split_turns(LEGIT_RECRUITER)
    assert len(t) == 3
    assert t[0]["who"].startswith("Maria Chen") and t[1]["who"].startswith("Evan Wilson")
    assert t[0]["text"].startswith("Hi Evan, I'm a campus recruiter")
    assert not t[1]["text"].startswith(">")
    assert t[2]["text"].startswith("Hi Evan,\n\nThanks for confirming")


def test_split_bare_quote_blocks():
    text = "Sure, send it over.\n\n> Can I send you the check today?\n>\n>> Are you still available for the job?"
    t = split_turns(text)
    assert [x["text"] for x in t] == ["Are you still available for the job?", "Can I send you the check today?",
                                      "Sure, send it over."]


def test_split_forwarded_message():
    text = ("Is this legit?\n\n---------- Forwarded message ---------\n"
            "From: HR Team <hiring.dept2026@gmail.com>\nDate: Mon, Oct 12, 2026 at 9:00 AM\nSubject: Job offer\n"
            "To: <evan.wilson@fsu.edu>\n\n"
            "You have been selected for a remote personal assistant role. Reply using your alternative email.")
    t = split_turns(text)
    assert len(t) == 2
    assert t[0]["text"].startswith("Job offer") and t[1]["text"] == "Is this legit?"
    assert t[0]["who"].startswith("HR Team")


# ---------------------------------------------------------------- stages

def test_stage_of_examples():
    assert stage_of("You have been selected through the School recruiting department. Earn $500 weekly.")["stages"][:2] == \
        ["hook", "legitimacy"]
    assert "channel_switch" in stage_of("Please contact me on Telegram @hr_kelly_")["stages"]
    assert "onboarding" in stage_of("Kindly fill the form below to confirm your full name and mailing address.")["stages"]
    assert "data_grab" in stage_of("What bank do you use?")["stages"]
    assert "ask" in stage_of("Deposit the check and buy 3 Apple gift cards.")["stages"]
    assert "pressure" in stage_of("You'll be charged if you don't finish this today.")["stages"]
    assert stage_of("Thanks, talk soon.")["stages"] == []
    assert set(STAGES) == {"hook", "legitimacy", "channel_switch", "onboarding", "data_grab", "ask", "pressure"}
    assert {s["id"] for s in SCRIPTS} >= {"fake_check", "task_scam", "reshipping", "gift_card_boss", "crypto_recruiter",
                                          "advance_fee_training", "identity_harvest"}


def test_gift_card_boss_and_crypto_threads():
    r = analyze_thread("Professor Hall: Are you available? I'm in a meeting and can't talk. I need a quick favor.\n\n"
                       "Me: Sure\n\n"
                       "Professor Hall: Please buy 4 Apple gift cards ($100 each) for client gifts and send me the codes.")
    assert r["script"] == "gift_card_boss" and r["risk"] == "high"
    r = analyze_thread("Recruiter: The Giving Block needs a Bitcoin ATM evaluator, $300 weekly.\n\n"
                       "Me: ok\n\nRecruiter: Deposit the $900 we send you into the Bitcoin ATM near you.")
    assert r["script"] == "crypto_recruiter" and r["risk"] == "high"


def test_advance_fee_thread():
    r = analyze_thread("Recruiter: Congratulations, you have been hired as a Certified Crypto Analyst, no interview required.\n\n"
                       "Me: thanks!\n\n"
                       "Recruiter: You must first obtain our $180 certification before your onboarding call. "
                       "Pay the $180 training fee via Cash App today.")
    assert r["script"] == "advance_fee_training" and r["risk"] == "high"


# ---------------------------------------------------------------- guards

@pytest.mark.parametrize("text", [
    "We will never ask you to pay for training or a registration fee.",
    "At no time will we ask you to deposit a check, buy gift cards or send money by Zelle.",
    "You will never be asked to deposit checks or send money. Register free on our site.",
    "If anyone asks you to buy gift cards or wire money, it's a scam. Report it to the career center.",
    "Background check and drug screen are paid by the agency. Direct deposit is set up after your offer.",
    "The background check fee is paid by us.",
    "There is no application fee and no training fee. Paid training is provided at no cost.",
    "New hires complete the I-9 and W-4 and provide their Social Security number for payroll upon hire.",
    "After you accept the offer, HR will collect your routing number and account number for direct deposit.",
    "Payment through Cash App, Venmo, or PayPal.",
    "I will send the money via PayPal after the report is approved.",
    "You will receive payments through direct deposit to your bank account every week after your first completed delivery.",
    "Experience with cryptocurrency markets, bitcoin and ethereum node operations preferred.",
    "Wellness program with gift card redemption and wellness challenges.",
    "Must possess a valid driver's license.",
    "Receive, sort, and distribute incoming mail and packages; prepare outgoing mail and shipments.",
    "Processing of vendor invoice payments to the servicing system daily.",
])
def test_guards_block_legit_wording(text):
    money = [a for a in extract_asks(text) if a["ask"] in MONEY_ASKS]
    assert money == [], money


@pytest.mark.parametrize("text,ask", [
    ("No experience needed, but you must pay a $50 registration fee.", "pay_fee"),
    ("We will mail you a check to purchase your home office equipment.", "deposit_check"),
    ("Kindly proceed to make a mobile deposit.", "deposit_check"),
    ("Deposit the check and forward the balance to our equipment vendor.", "send_money_on"),
    ("You're to make a payment worth $719 to the zelle information below.", "send_money_on"),
    ("Purchase equipment from our approved vendor.", "buy_equipment"),
    ("Buy 4 Apple gift cards ($100 each) and send us the codes.", "gift_cards"),
    ("Evaluate a Bitcoin ATM around your location.", "crypto"),
    ("Receive packages at home, print labels, and reship them.", "reship"),
    ("Customers pay into your personal account; you transfer 90% to our partner account and keep 10% commission.",
     "receive_transfers"),
    ("To unlock your withdrawal you will need to top up your account with USDT.", "task_deposit"),
    ("Please provide a valid account and routing number.", "bank_details"),
    ("Please send me a scan of your driver's license and your SSN.", "identity_docs"),
    ("Message our manager on Telegram @hr_kelly_ to start today.", "move_off_platform"),
    ("Send your resume using your alternative email, not your school email.", "personal_email_reply"),
    ("Slots are limited, first come first serve.", "urgency"),
    ("Interview will be conducted via chat only.", "no_interview"),
    ("Download AnyDesk so I can set up your workstation.", "install_app"),
])
def test_asks_fire_on_scam_wording(text, ask):
    found = extract_asks(text)
    assert ask in {a["ask"] for a in found}
    hit = next(a for a in found if a["ask"] == ask)
    assert hit["evidence"] and hit["evidence"].lower() in text.lower().replace("’", "'")
    assert set(hit) >= {"ask", "label", "evidence"}


def test_ask_taxonomy_is_complete():
    assert set(ask_ids()) == {"pay_fee", "buy_equipment", "deposit_check", "send_money_on", "gift_cards", "crypto",
                              "reship", "receive_transfers", "task_deposit", "move_off_platform", "bank_details",
                              "identity_docs", "personal_email_reply", "urgency", "no_interview", "install_app"}


# ---------------------------------------------------------------- labeled data

FP_ASKS = ["pay_fee", "deposit_check", "send_money_on", "gift_cards", "crypto", "reship", "receive_transfers",
           "task_deposit", "bank_details", "identity_docs"]


def _labeled_rows():
    seen, rows = set(), []
    for path in sorted(glob.glob(os.path.join(DATA_DIR, "*.jsonl"))):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                label = r.get("label")
                if label not in ("legit", "scam"):
                    continue
                text = (r.get("title") or "") + "\n" + (r.get("description") or "")
                if (label, text) in seen:
                    continue
                seen.add((label, text))
                rows.append((label, text))
    return rows


def test_money_asks_rarely_fire_on_labeled_legit_rows():
    rows = _labeled_rows()
    counts = {"legit": collections.Counter(), "scam": collections.Counter()}
    n = collections.Counter()
    fp_rows = 0
    for label, text in rows:
        n[label] += 1
        ids = {a["ask"] for a in extract_asks(text)}
        counts[label].update(ids)
        if label == "legit" and ids & set(FP_ASKS):
            fp_rows += 1
    print(f"\nlabeled rows: {dict(n)}")
    print(f"{'ask':20} {'legit':>6} {'scam':>6}")
    for a in ask_ids():
        print(f"{a:20} {counts['legit'][a]:>6} {counts['scam'][a]:>6}")
    rate = fp_rows / max(1, n["legit"])
    print(f"legit rows with any money ask: {fp_rows}/{n['legit']} = {rate:.1%}")
    assert n["legit"] >= 100 and n["scam"] >= 50
    assert rate < 0.02
    for a in FP_ASKS:
        assert counts["legit"][a] / n["legit"] < 0.02, a
    scam_hits = sum(1 for label, text in rows
                    if label == "scam" and {x["ask"] for x in extract_asks(text)} & set(FP_ASKS))
    assert scam_hits / n["scam"] > 0.3
