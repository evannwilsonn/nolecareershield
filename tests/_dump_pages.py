import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from test_easy_network import *  # noqa
OUT = os.environ["DUMP"]

def test_dump(net):
    emp, eid = employer(net)
    job = easy_job(net, eid)
    a, aid, b, bid = two_students(net)
    c, cid = student(net, "c@fsu.edu", "Casey Rivera")
    ta, tb = ucsrf(a), ucsrf(b)
    a.post(f"/job/{job}/easy", data=apply_form(job, ta))
    b.post("/network/connect", data={"csrf": tb, "to": aid, "note": "Stats club, hi!"})
    c.post("/network/connect", data={"csrf": ucsrf(c), "to": aid})
    a.post("/network/follow", data={"csrf": ta, "employer": eid})
    pages = {"form": (b, f"/job/{job}/easy"), "job": (b, f"/job/{job}"), "net_req": (a, "/network?tab=requests"), "net_disc": (a, "/network?tab=discover"),
             "net_fol": (a, "/network?tab=following"), "apps": (a, "/applications"), "cands": (emp, f"/hiring/{job}?tab=candidates"),
             "post": (emp, "/post"), "company": (a, f"/company/{eid}"), "profile": (b, f"/u/{aid}"), "jobs": (a, "/jobs")}
    for k, (cl, path) in pages.items():
        open(f"{OUT}/{k}.html", "w").write(cl.get(path).text)
