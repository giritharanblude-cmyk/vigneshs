import json
d = json.load(open("data/processed/dashboard_data.json"))
print("=== Longitudinal metrics per skill ===\n")
n_with = 0
for t in d["trends"]:
    yoy = t.get("yoy_growth")
    mom = t.get("mom_growth")
    roll = t.get("rolling_12m_change")
    share = t.get("skill_share")
    shchg = t.get("share_change")
    has = any(v is not None for v in (yoy, mom, roll, share, shchg))
    if has:
        n_with += 1
    f = lambda v: (round(v,1) if v is not None else "-")
    print("{:20} yoy={:>6} mom={:>7} roll={:>7} share={:>6} shchg={:>6}".format(
        t["skill_name"], f(yoy), f(mom), f(roll), f(share), f(shchg)))
print("\nSkills with >=1 longitudinal metric:", n_with, "of", len(d["trends"]))
print("\n=== Monthly trend series (first 2 skills) ===")
for entry in d["monthly_data"][:2]:
    print(entry["skill"], "->", entry["series"])
