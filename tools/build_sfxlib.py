"""Build assets/sfxlib from the user's SFX packs (velic/sfx_packs): short files only, categorised by filename,
re-encoded small (mono mp3, peak-normalised). Writes assets/sfxlib/catalog.json [{id, cat, dur, file}]."""
import json, re, subprocess, sys, hashlib
from pathlib import Path

SRC = Path("D:/oat/tools/hermes/marketing/velic/sfx_packs")
DUR = Path("D:/oat/tools/hermes/cache/scratch/sfx_dur.txt")
OUT = Path(__file__).resolve().parent.parent / "assets" / "sfxlib"
OUT.mkdir(parents=True, exist_ok=True)

CATS = [  # order matters: first match wins
    ("vineboom", r"vine.?boom"),
    ("bruh", r"bruh"),
    ("metal_pipe", r"metal.?pipe"),
    ("fart", r"fart|kentut"),
    ("laugh", r"laugh|giggle|haha|hehe|chuckle"),
    ("fail", r"oof|emotional.?damage|wasted|fail|sad|augh|aaugh|oh.?no|disappoint|its.?over|it_s.?over|wrong|lose|error|womp|trombone|cry"),
    ("shock", r"gasp|shock|surpris|wait|what|huh|siren|alert|alarm|scream|omg|oh.?my|ayo|dun.?dun|jumpscare|scare"),
    ("whoosh", r"whoosh|swish|swoosh|woosh|transition|swipe|fast.?pass|zoom"),
    ("impact", r"boom|impact|hit|punch|thud|slam|explos|sub.?drop|bonk|smack|crash|bang|kick|slap|thump"),
    ("pop", r"pop|click|blink|bubble|plop"),
    ("ding", r"ding|bell|chime|notif|correct|tada|ta.?da"),
    ("win", r"cash|coin|money|win|victory|level.?up|yay|cheer|applause|sheesh|sigma|sparkle|success|bonus|reward"),
    ("bounce", r"boing|bounce|spring|jump|cartoon|zip|spin|wobble"),
    ("run", r"run|walk|step|footstep|tip.?toe"),
    ("magic", r"magic|glitch|teleport|power|laser|zap|electric|beam|warp|charge"),
    ("riser", r"riser|suspense|heartbeat|tick|drum.?roll|tension|build"),
    ("game", r"roblox|minecraft|mario|game|arcade|8.?bit|retro|death|respawn"),
    ("animal", r"cat|dog|bark|meow|duck|chicken|cow|goat|bird|monkey|bear"),
    ("voice_meme", r"no.?no|bro|sus|nope|yes|lets.?go|let_s.?go|nice|easy|okay|hello|bye|why|stop|help|run"),
]

rows = []
seen = set()
for line in DUR.read_text(encoding="utf-8").splitlines():
    d, _, f = line.partition("|")
    try:
        d = float(d)
    except ValueError:
        continue
    if not (0.15 <= d <= 4.0):
        continue
    name = Path(f).stem
    low = re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()
    cat = next((c for c, rx in CATS if re.search(rx, low.replace(" ", "_")) or re.search(rx, low)), None)
    if not cat:
        continue
    clean = re.sub(r"\b(sound|effect|effects|sfx|meme|mp3|hd|free|download|copyright|no|template|converttoaudio|\d{3,})\b", " ", low)
    clean = re.sub(r"\s+", "_", clean).strip("_")[:40] or cat
    key = (clean, round(d, 1))
    if key in seen:
        continue
    seen.add(key)
    sid = clean
    n = 2
    while any(r["id"] == sid for r in rows):
        sid = f"{clean}_{n}"; n += 1
    rows.append({"id": sid, "cat": cat, "dur": round(d, 2), "src": f})

print(len(rows), "files")
ok = []
for r in rows:
    dst = OUT / f"{r['id']}.mp3"
    if not dst.exists():
        p = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(SRC / r["src"]), "-ac", "1", "-ar", "44100",
                            "-af", "silenceremove=start_periods=1:start_threshold=-45dB,dynaudnorm=p=0.9:m=10,alimiter=limit=0.9",
                            "-b:a", "80k", str(dst)], capture_output=True)
        if p.returncode or not dst.exists() or dst.stat().st_size < 1500:
            dst.unlink(missing_ok=True); continue
    ok.append({"id": r["id"], "cat": r["cat"], "dur": r["dur"], "file": dst.name})
(OUT / "catalog.json").write_text(json.dumps(ok, ensure_ascii=False, indent=0), encoding="utf-8")
from collections import Counter
print(len(ok), Counter(x["cat"] for x in ok).most_common())
