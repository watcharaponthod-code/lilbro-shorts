"""One 1-2 minute Roblox story Short per run ("In this world, ..." format, modeled on ItsGuestCap / playit hits):
pick a theme (test & learn), write the story, make 8-12 meta.ai clips that look like real 3D Roblox footage, fast Microsoft
Edge narration + 2-4 word captions + SFX + music, upload to YouTube through Maton, log for learning.

Run (Actions):  python make.py            env: META_COOKIES, MATON_API_KEY, MATON_YT_MONKEY_CONNECTION
Local test:     python make.py --script test/script.json --clips test/clips --no-upload
"""
import argparse, asyncio, datetime as dt, json, math, os, random, re, shutil, subprocess, sys, time, wave
from pathlib import Path

import numpy as np
import requests

D = Path(__file__).parent
STATE = D / "state"
FF = os.environ.get("FFMPEG", "ffmpeg")
FP = os.environ.get("FFPROBE", "ffprobe")
VOICES = {  # name: (edge voice, rate, pitch, pitch-shift factor applied by ffmpeg)
    "guy_high": ("en-US-GuyNeural", "+30%", "+40Hz", 1.0),                    # matches the reference narrator (F0 ~190 Hz, bright)
    "christopher_hard": ("en-US-ChristopherNeural", "+40%", "-6Hz", 1.0),      # deep, hard-hitting narrator (default)
    "guy_hard": ("en-US-GuyNeural", "+40%", "-8Hz", 1.0),
    "brian_fast": ("en-US-BrianMultilingualNeural", "+45%", "+0Hz", 1.0),       # ~220 wpm like the reference narrators
    "andrew_fast": ("en-US-AndrewMultilingualNeural", "+55%", "+0Hz", 1.0),
    "andrew_chipmunk": ("en-US-AndrewMultilingualNeural", "+10%", "+0Hz", 1.35),
    "guy_squeaky": ("en-US-GuyNeural", "+12%", "+20Hz", 1.25),
    "ana_kid": ("en-US-AnaNeural", "+10%", "+0Hz", 1.0),
    "ana_squeak": ("en-US-AnaNeural", "+8%", "+10Hz", 1.15),
}
VOICE, RATE, PITCH, SHIFT = VOICES[os.environ.get("VOICE_PRESET", "guy_high")]
EDGE_SR = 24000  # edge-tts mp3 sample rate
CHANNEL_ID = "UCczRwdCgEiEsXG-6Ji2mWew"  # Lil Bro Chaos (monkey connection); abort if Maton points elsewhere
GW = "https://gateway.maton.ai/youtube"
FONT = os.environ.get("FONT_NAME", "Archivo Black")

STYLE = ("Classic 2D TV cartoon animated on twos at 12 frames per second, like an old-school hand-drawn Saturday-morning "
         "cartoon: thick uniform black outlines, flat cel colors, painted backgrounds, snappy limited animation with held poses. "
         "All characters are ROBLOX avatars drawn as 2D cartoons: blocky square heads, rectangular blocky bodies and limbs, "
         "simple Roblox faces, Roblox hair and outfits. Not 3D, not CGI. No channel logos, no watermark.")
SFXLIB = D / "assets" / "sfxlib"
CATALOG = jload_early = json.loads((SFXLIB / "catalog.json").read_text(encoding="utf-8")) if (SFXLIB / "catalog.json").exists() else []
CATALOG += [{"id": f.stem, "cat": "meme", "dur": 1, "file": str(f)} for f in sorted((D / "assets" / "sfx").glob("*.wav"))]
SFX_CATS = sorted({c["cat"] for c in CATALOG} - {"whoosh"})


def sfx_menu(k=10):
    rnd = random.Random(7)
    out = []
    for cat in SFX_CATS:
        ids = [c["id"] for c in CATALOG if c["cat"] == cat]
        out.append(f"{cat}: " + ", ".join(rnd.sample(ids, min(k, len(ids)))))
    return "\n".join(out)


def sfx_file(name):
    """exact id -> that file; category -> random file of it; else fuzzy contains; else a pop."""
    name = (name or "").strip().lower()
    hit = [c for c in CATALOG if c["id"] == name] or [c for c in CATALOG if c["cat"] == name] or \
          [c for c in CATALOG if name and (name in c["id"] or c["id"] in name)] or [c for c in CATALOG if c["cat"] == "pop"]
    c = random.choice(hit)
    p = Path(c["file"])
    return p if p.is_absolute() else SFXLIB / p
CHAN_RULES = """Audience: kids and teens (8-16) who play Roblox. Format = the viral Roblox story Shorts "In this world..." (ItsGuestCap
'In this world everyone can see your lies' 36M views, playit 'Step On A Crack Break Your Moms BACK' 15M views):
- Line 1 states the world's one RULE, and it must be WILD, surreal and never seen before: beyond imagination, not an
  everyday or school/family cliche. Good: "In this world, your shadow is a separate person who can quit", "In this world, the
  moon is a giant egg and tonight it hatches", "In this world, every time you blink, a random city swaps places with yours",
  "In this world, gravity belongs to whoever owns the most cats". Bad (too ordinary, never use): grades, lies, homework,
  siblings swapping, chores, phones, mom rules, superstitions everyone knows. Then 3-5 fast, absurd examples of daily life
  under that rule, each crazier than the last.
- Hook style that goes viral (Tyler 'Every Kid He Takes Home D*ES...' 7.4M): the first line sounds dark, shocking and
  mysterious ("This man adopted ten kids, and not a single one is still alive"), then the story slowly reveals a surprising
  truth that flips it (often heartwarming). Keep the surreal rule, but tell it with this creepy-mystery tension.
- Then a main kid (named, e.g. Dylan) and his situation under the rule; a rival or outsider; a problem/conflict that escalates.
- A twist that flips what we believed (the 'liar' was taking the blame for everyone), and a payoff: emotional or hilarious,
  with a callback to an early joke in the last line. Never reveal the twist early.
- Narration is fast, plain spoken, short sentences, concrete numbers and details, some dialogue in quotes. No moralizing speech."""


def sh(*a, **k):
    return subprocess.run([str(x) for x in a], check=True, **k)


def dur(p):
    return float(subprocess.run([FP, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                                capture_output=True, text=True).stdout.strip() or 0)


def jload(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default


# ---------------------------------------------------------------- LLM (GitHub Models; fallback list of models)
def llm_json(prompt, temp=1.0):
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_MODELS_TOKEN")
    last = None
    for model in ["openai/gpt-4.1", "openai/gpt-4o", "openai/gpt-4.1-mini", "openai/gpt-4o-mini"]:
        for attempt in range(2):
            try:
                r = requests.post("https://models.github.ai/inference/chat/completions", timeout=120,
                                  headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
                                  json={"model": model, "temperature": temp, "response_format": {"type": "json_object"},
                                        "messages": [{"role": "user", "content": prompt}]})
                if r.status_code != 200 or not r.headers.get("content-type", "").startswith("application/json"):
                    last = f"{model} {r.status_code} {r.text[:200]}"; break
                txt = r.json()["choices"][0]["message"]["content"]
                return json.loads(txt[txt.index("{"): txt.rindex("}") + 1])
            except Exception as e:
                last = f"{model} {e}"; time.sleep(3)
    print("GitHub Models failed:", last, "-> asking meta.ai")
    for attempt in range(2):                      # fallback: meta.ai text chat with the same login
        pf, of = D / "work" / "llm_prompt.txt", D / "work" / "llm_out.json"
        pf.parent.mkdir(exist_ok=True)
        pf.write_text(prompt + "\nReply with ONLY the JSON object, no markdown, no extra text.", encoding="utf-8")
        of.unlink(missing_ok=True)
        subprocess.run(["node.exe" if os.name == "nt" else "node", str(D / "ask_meta.mjs"), str(pf), str(of)], check=False, timeout=400)
        if of.exists():
            return json.loads(of.read_text(encoding="utf-8"))
    raise RuntimeError("LLM failed: " + str(last))


# ---------------------------------------------------------------- Maton / YouTube
def maton_h():
    return {"Authorization": f"Bearer {os.environ['MATON_API_KEY']}", "Maton-Connection": os.environ["MATON_YT_MONKEY_CONNECTION"]}


def refresh_stats(hist):
    ids = [h["id"] for h in hist if h.get("id")][-50:]
    if not ids:
        return
    try:
        r = requests.get(f"{GW}/youtube/v3/videos", params={"part": "statistics", "id": ",".join(ids)}, headers=maton_h(), timeout=60)
        st = {x["id"]: x["statistics"] for x in r.json().get("items", [])}
    except Exception as e:
        print("stats failed", e); return
    now = time.time()
    for h in hist:
        if h.get("id") in st:
            v = int(st[h["id"]].get("viewCount", 0)); age = (now - h["t"]) / 60
            h["views"] = v; h["likes"] = int(st[h["id"]].get("likeCount", 0)); h["age_min"] = round(age)
            h.setdefault("checks", []).append([round(age), v])
            h["checks"] = h["checks"][-12:]


def upload(final, s):
    # English-only metadata: the channel targets a worldwide audience, so no Thai (or any other) localization is ever set
    en = lambda x: re.sub(r"\s+", " ", re.sub(r"[^\x00-\u024F\u2010-\u2027]+", "", str(x))).strip()
    desc = re.sub(r"#\s+(?=\w)", "#", en(s.get("description", "")))
    if "#shorts" not in desc.lower():
        desc += " #roblox #shorts #robloxstory #robloxanimation"
    tags = [t for t in (en(t).replace("<", "").replace(">", "")[:30] for t in (s.get("tags") or [])) if t][:15] or \
        ["roblox", "roblox story", "roblox animation", "roblox shorts", "in this world"]
    meta = {"snippet": {"title": en(s["title"])[:100], "description": desc[:4900], "tags": tags,
                        "categoryId": "1", "defaultLanguage": "en", "defaultAudioLanguage": "en"},
            "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False, "containsSyntheticMedia": False}}
    cr = requests.get(f"{GW}/youtube/v3/channels", params={"part": "id", "mine": "true"}, headers=maton_h(), timeout=60)
    if cr.status_code == 429 or "quota" in cr.text.lower():
        raise UploadLimit(f"maton quota ({cr.status_code}): {cr.text[:160]}")
    ch = cr.json() if cr.headers.get("content-type", "").startswith("application/json") else {}
    cid = (ch.get("items") or [{}])[0].get("id")
    if cid is None:
        raise RuntimeError(f"channel check failed {cr.status_code} {cr.text[:200]}")
    if cid != CHANNEL_ID:
        raise SystemExit(f"wrong channel {cid}, refusing to upload")
    bd = "mtn" + os.urandom(12).hex()
    body = (f"--{bd}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{json.dumps(meta)}\r\n--{bd}\r\n"
            f"Content-Type: video/mp4\r\n\r\n").encode() + Path(final).read_bytes() + f"\r\n--{bd}--\r\n".encode()
    r = requests.post(f"{GW}/upload/youtube/v3/videos?uploadType=multipart&part=snippet,status", data=body, timeout=600,
                      headers={**maton_h(), "Content-Type": f"multipart/related; boundary={bd}"})
    j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if "uploadLimitExceeded" in r.text or (r.status_code == 429 and "quota" in r.text.lower()):
        raise UploadLimit(f"upload limited ({r.status_code}): {r.text[:160]}")
    if not j.get("id"):
        raise RuntimeError(f"upload failed {r.status_code} {r.text[:400]}")
    return j["id"]


class UploadLimit(Exception):
    pass


# ---------------------------------------------------------------- upload queue (GitHub releases "q-*")
REPO = os.environ.get("GITHUB_REPOSITORY", "watcharaphon-dotcom/lilbro-shorts")


def gh(*a, **k):
    return subprocess.run(["gh", *map(str, a), "-R", REPO], capture_output=True, text=True, encoding="utf-8", **k)


def queued():
    r = gh("release", "list", "--limit", "50", "--json", "tagName")
    return sorted(x["tagName"] for x in json.loads(r.stdout or "[]") if x["tagName"].startswith("q-"))


def enqueue(final, s, why, stamp):
    tag = f"q-{stamp}"
    meta = Path(final).parent / "queue_meta.json"
    meta.write_text(json.dumps({"script": s, "why": why}, ensure_ascii=False), encoding="utf-8")
    r = gh("release", "create", tag, str(final), str(meta), "--title", tag, "--notes", s["title"], "--prerelease")
    print("queued", tag, r.returncode, r.stderr[:200])


def drain_queue(hist):
    """upload queued videos oldest first; returns True if YouTube is still limiting uploads."""
    for tag in queued():
        d = D / "work" / tag; d.mkdir(parents=True, exist_ok=True)
        gh("release", "download", tag, "-D", str(d), "--clobber")
        m = jload(d / "queue_meta.json", None)
        if not m or not (d / "final.mp4").exists():
            gh("release", "delete", tag, "--yes", "--cleanup-tag"); continue
        try:
            vid = upload(d / "final.mp4", m["script"])
        except UploadLimit:
            print("still limited; queue:", tag); return True
        print("UPLOADED from queue", vid, m["script"]["title"])
        hist.append({"id": vid, "t": time.time(), "format": m["script"]["format"], "title": m["script"]["title"],
                     "why": m.get("why", "") + "+queued"})
        gh("release", "delete", tag, "--yes", "--cleanup-tag")
        return True        # one upload per run is enough; keeps the hourly pace
    return False


# ---------------------------------------------------------------- format choice (test & learn)
def score(h):
    """views per hour, judged at the latest check (penalise very young videos less: use age >= 20 min)."""
    if not h.get("views") and h.get("views") != 0:
        return None
    age = max(h.get("age_min", 0), 20) / 60
    return h["views"] / age


def pick_format(formats, hist):
    stats = {}
    for h in hist:
        sc = score(h)
        if sc is not None and h.get("age_min", 0) >= 20:
            stats.setdefault(h["format"], []).append(sc)
    active = [f for f in formats if not f.get("retired")]
    untried = [f for f in active if f["id"] not in stats]
    # retire formats that had >=3 tries and are in the bottom half
    if len(stats) >= 4:
        med = sorted(np.mean(v) for v in stats.values())[len(stats) // 2]
        for f in active:
            v = stats.get(f["id"], [])
            if len(v) >= 3 and np.mean(v) < 0.5 * med:
                f["retired"] = True; print("retire format", f["id"])
    r = random.random()
    if untried and (r < 0.6 or not stats):
        return random.choice(untried), "explore-untried"
    if r < 0.2 or not stats:
        return None, "invent"            # caller invents a brand-new format
    best = max((f for f in active if f["id"] in stats and not f.get("retired")),
               key=lambda f: np.mean(sorted(stats[f["id"]])[-5:]), default=None)
    return (best, "exploit") if best else (random.choice(active), "random")


def invent_format(formats, hist):
    top = sorted([h for h in hist if h.get("views") is not None], key=lambda h: -h["views"])[:5]
    j = llm_json(f"""You run a YouTube Shorts channel of Roblox story videos. {CHAN_RULES}
Existing formats (id: idea): {json.dumps({f['id']: f['idea'] for f in formats})}
Our best videos so far: {json.dumps([{k: h.get(k) for k in ('title', 'format', 'views', 'age_min')} for h in top])}
Invent ONE new THEME family of "In this world..." rules, different from the existing ones: surreal, mind-bending,
beyond imagination (cosmic, impossible physics, living objects, monsters, time, dreams, giant creatures), never ordinary
school/family/phone topics. Kids 8-16 must think "WHAT?" in the first second.
Return JSON {{"id": "snake_case_id", "idea": "one sentence describing the kind of rule and story, with an example rule", "title_pattern": "example title"}}""")
    j["id"] = re.sub(r"[^a-z0-9_]", "", j["id"].lower())[:40] or f"fmt{len(formats)}"
    j["invented"] = dt.datetime.utcnow().isoformat()[:16]
    return j


ORIGINAL_RULES = """Audience: kids and teens (8-16) who play Roblox. This is the channel's OWN series, not a copy of any
other channel's format: never open with "In this world", never use "Noob vs Pro vs Hacker", "POV:", or any known template.
- Told in FIRST PERSON by the narrator named in the theme, like a kid telling a friend what just happened. Plain, fast, funny.
- Line 1 is the whole premise in one concrete sentence with a number in it, so a viewer gets it in 2 seconds.
- Everything is built on real Roblox things kids know: respawn, admin commands, Robux, obbies, lag, servers, lobbies, NPCs,
  game passes, the void, leaderboards. Use them literally, as if they are real life.
- One problem that gets worse three times, each step bigger and sillier than the last, with exact numbers.
- Last scene: a twist that flips the story, then a final line that calls back to line 1. No moral, no lesson.
- Recurring cast (keep these exact looks whenever they appear): Lil Bro = 6-year-old tiny Roblox avatar, round yellow head,
  huge red hoodie down to his knees, one missing front tooth, always holding a half-eaten cookie. Dylan = his 11-year-old
  big brother, messy black hair, white puffer jacket, blue jeans."""


def write_script(fmt, hist):
    recent = [h["title"] for h in hist[-40:]]
    own = fmt.get("style") == "original"
    n = random.choice(fmt.get("scenes") or [8, 9, 10, 11])      # ~10 s per scene
    rules = ORIGINAL_RULES if own else CHAN_RULES
    opener = ("Scene 1 opens with the premise line in first person (never \"In this world\")." if own else
              "Scene 1 opens with the shocking mysterious hook line (start it with \"In this world,\" and state the rule in the first sentence).")
    title_rule = (f"Title Case title in first person that states the premise plainly, max 60 chars, like '{fmt.get('title_pattern', '')}'; never starts with 'In This World'; no emoji, no ellipsis, never the word AI"
                  if own else
                  "Title Case title that starts with 'In This World' and states the strange rule plainly, max 70 chars, like 'In This World Every Sneeze Hatches A Kaiju' or 'In This World Siblings Swap Bodies When They Fight'; no emoji, no ellipsis, never the word AI")
    j = llm_json(f"""Write a {n * 10}-second YouTube Short story told over real 3D ROBLOX gameplay footage. Theme: {fmt['idea']}
{rules}
Exactly {n} scenes. Each scene = ~10 seconds of video and the narration spoken over it.
- "say": the narrator text for this scene, 30-36 words (spoken fast, ~220 words per minute). {opener}
  All scenes together must read as one continuous story.
- "video": what is SEEN in this 10 s as Roblox footage: location, which characters (by name), the action in order, and
  2-3 camera cuts written as [0-4s] ... [4-7s] ... [7-10s] .... Show the rule visually (e.g. floating numbers above heads).
  No speech bubbles, no captions.
- "sfx": 0-2 sound effects for big funny/dramatic moments, as [{{"name": "...", "at": seconds 0-10}}]; exact name or category from:
{sfx_menu(6)}
"characters": every named character with a FIXED look as Roblox avatar (age, hair, clothes, colors), so each separately generated
scene keeps them identical.
Do NOT reuse these recent titles/ideas: {json.dumps(recent)}
Return JSON: {{"title": "{title_rule}",
"description": "1 line hook + 1 question for viewers, then: #roblox #shorts #robloxstory #robloxanimation",
"music_mood": "the background music that fits the WHOLE story's tone: funny (light comedy), mystery (curious/suspense), dramatic (tension, conflict), emotional (sad/heartfelt twist), epic (big competition/climax)",
"tags": ["15 search tags"], "characters": {{"Dylan": "11-year-old Roblox boy, messy black hair, white puffer jacket, blue jeans"}},
"scenes": [{{"say": "...", "video": "...", "sfx": [{{"name": "shock", "at": 6}}]}}]}}""")
    assert len(j["scenes"]) >= min(6, n), f"need {min(6, n)}+ scenes"
    j["title"] = re.sub(r"\bAI\b", "", j["title"])
    j["title"] = re.sub(r"[^\x00-\u024F]+", "", j["title"]).replace("...", " ").strip(" .")
    if own:
        j["title"] = re.sub(r"(?i)^in this world,?\s*", "", j["title"])
    j["title"] = re.sub(r"\s+", " ", j["title"])
    return j


def video_prompt(sc, chars=None):
    # every scene is generated in a separate chat, so repeat the exact look of each named character it shows
    chars = {str(k).strip(): v for k, v in (chars or {}).items() if str(k).strip()}
    who = [f"{k}: {v}" for k, v in chars.items() if re.search(rf"\b{re.escape(k)}\b", sc["video"], re.I)]
    looks = (" Characters (keep these exact looks): " + "; ".join(who) + ".") if who else ""
    return (f"Create a 10-second vertical 9:16 video. {STYLE}{looks} {sc['video']} Animated on twos (12 fps) with the camera "
            f"cuts. No captions, no speech bubbles, no text except numbers or signs that are part of the story. AUDIO: no dialogue, no music.")


# ---------------------------------------------------------------- audio: TTS, SFX, music
async def _tts(text, out):
    import edge_tts
    c = edge_tts.Communicate(text, VOICE, rate=RATE, pitch=PITCH, boundary="WordBoundary")
    words, audio = [], bytearray()
    async for ch in c.stream():
        if ch["type"] == "audio":
            audio += ch["data"]
        elif ch["type"] == "WordBoundary":
            words.append({"w": ch["text"], "s": ch["offset"] / 1e7, "e": (ch["offset"] + ch["duration"]) / 1e7})
    Path(out).write_bytes(bytes(audio))
    return words


def tts_cf(text, out):
    """Cloudflare Workers AI Deepgram Aura-2 'zeus' via the worker's /tts route (the voice the user prefers).
    Aura has no word timings, so caption timing is spread over the words by length."""
    url, tok = os.environ.get("WORKER_URL"), os.environ.get("ADMIN_TOKEN")
    if not url or not tok:
        return None
    for a in range(3):
        try:
            r = requests.post(url.rstrip("/") + "/tts", json={"text": text, "speaker": os.environ.get("AURA_SPEAKER", "zeus")},
                              headers={"Authorization": f"Bearer {tok}"}, timeout=120)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("audio") and len(r.content) > 2000:
                raw = Path(out).with_suffix(".raw.mp3"); raw.write_bytes(r.content)
                # trim leading/trailing silence so scenes flow tightly
                sh(FF, "-v", "error", "-y", "-i", raw, "-af", "silenceremove=start_periods=1:start_threshold=-45dB,areverse,"
                   "silenceremove=start_periods=1:start_threshold=-45dB,areverse", "-ar", "24000", "-ac", "1", out)
                d = dur(out); ws = text.split(); w8 = [len(x) + 2 for x in ws]; tot = sum(w8); t = 0.0; words = []
                for x, k in zip(ws, w8):
                    words.append({"w": x, "s": d * t / tot, "e": d * (t + k) / tot}); t += k
                return words
            print("aura failed", r.status_code, r.text[:150])
        except Exception as e:
            print("aura error", e)
        time.sleep(3)
    return None


def tts(text, out):
    if os.environ.get("TTS", "edge") == "cf":
        w = tts_cf(text, out)
        if w is not None:
            return w
        print("Cloudflare TTS unavailable -> Edge fallback")
    for a in range(6):
        try:
            return asyncio.run(_tts(text, out))
        except Exception as e:
            print("tts retry", a, type(e).__name__); time.sleep(3 * (a + 1))
    raise RuntimeError("edge tts failed")


def synth_sfx(dirp):
    """whoosh/pop/ding/boom/riser synthesised (no licensing); meme pack wavs come from assets/sfx."""
    sr = 48000; rng = np.random.default_rng(1)
    def save(name, x):
        x = (np.clip(x / (np.abs(x).max() + 1e-9), -1, 1) * 0.9 * 32767).astype(np.int16)
        with wave.open(str(dirp / f"{name}.wav"), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(x.tobytes())
    t = np.arange(int(sr * 0.45)) / sr
    n = rng.standard_normal(len(t)); env = np.sin(np.pi * t / t[-1]) ** 2
    k = np.exp(-((np.arange(-200, 201) / 60) ** 2)); save("whoosh", np.convolve(n, k / k.sum(), "same") * env * (1 + 3 * t))
    t = np.arange(int(sr * 0.12)) / sr; save("pop", np.sin(2 * np.pi * (900 - 4000 * t) * t) * np.exp(-t * 40))
    t = np.arange(int(sr * 0.8)) / sr; save("ding", (np.sin(2 * np.pi * 1320 * t) + 0.5 * np.sin(2 * np.pi * 2640 * t)) * np.exp(-t * 5))
    t = np.arange(int(sr * 1.0)) / sr; save("boom", (np.sin(2 * np.pi * (60 * np.exp(-t * 2)) * t) + 0.3 * rng.standard_normal(len(t)) * np.exp(-t * 8)) * np.exp(-t * 3))
    t = np.arange(int(sr * 1.2)) / sr; save("riser", np.convolve(rng.standard_normal(len(t)), np.ones(30) / 30, "same") * (t / t[-1]) ** 2 + 0.3 * np.sin(2 * np.pi * (200 + 600 * t) * t) * t)


def ts(x):
    x = max(0, x); return f"{int(x // 3600)}:{int(x % 3600 // 60):02d}:{x % 60:05.2f}"


# ---------------------------------------------------------------- assemble
def assemble(s, clips, work):
    work.mkdir(parents=True, exist_ok=True)
    segs, events, speech, sfx, t = [], [], [], [], 0.0
    for i, (sc, clip) in enumerate(zip(s["scenes"], clips)):
        if clip is None:
            continue
        full = min(dur(clip), 10.5)
        mp3 = work / f"vo{i}.mp3"; W = tts(sc["say"], mp3); vd = dur(mp3)
        base = float(os.environ.get("VO_SPEED", "1.15" if os.environ.get("TTS", "edge") == "cf" else "1.0"))   # Aura-2 zeus sped up ~15% (punchy, like the first channel voice)
        tempo = min(1.3, max(base, vd / (full * 1.12)))   # narration drives the timing, like the reference shorts
        sd = vd / tempo
        seg_len = max(3.0, sd + 0.12)
        cd = min(full, seg_len)
        stretch = max(1.0, seg_len / cd)              # slow the clip a little if the line runs past it
        segs.append((clip, cd, stretch))
        st = t + 0.04
        speech.append((st, mp3, tempo, sd))
        sw = sc["say"].split()
        if len(W) != len(sw):
            a, b = (W[0]["s"], W[-1]["e"]) if W else (0.05, vd - 0.05); stp = (b - a) / len(sw)
            W = [{"w": x, "s": a + k * stp, "e": a + (k + 1) * stp} for k, x in enumerate(sw)]
        else:
            W = [{"w": x, "s": y["s"], "e": y["e"]} for x, y in zip(sw, W)]
        keys = {k.upper().strip(".,!?") for kw in sc.get("keywords", []) for k in kw.split()}
        chunks, cur = [], []
        for wd in W:
            cur.append(wd)
            if len(cur) == 4 or wd["w"][-1] in ".,!?" or (len(cur) >= 3 and len(wd["w"]) > 5):
                chunks.append(cur); cur = []
        if cur: chunks.append(cur)
        for k, ch in enumerate(chunks):
            s0 = st + ch[0]["s"] / tempo
            e0 = st + (chunks[k + 1][0]["s"] / tempo if k + 1 < len(chunks) else ch[-1]["e"] / tempo + 0.3)
            words = [x["w"] for x in ch]
            col = ["{\\c&H00E5FF&}", "{\\c&H4CFF4C&}", "{\\c&HCC66FF&}", "{\\c&H3C3CFF&}"][len(events) % 4]
            if len(words) >= 2 and (len(events) % 2 == 0 or words[-1][-1:] in ".!?"):   # key word in CAPS + color, like the reference
                words[-1] = col + words[-1].upper() + "{\\c&HFFFFFF&}"
            if len(words) >= 3:
                txt = " ".join(words[:len(words) // 2]) + "\\N" + " ".join(words[len(words) // 2:])
            else:
                txt = " ".join(words)
            events.append((s0, e0, "Word", txt))
        if i > 0 and random.random() < 0.35:
            sfx.append((max(0, t - 0.25), sfx_file("whoosh"), 0.25))
        cues = sc.get("sfx") or []
        if isinstance(cues, str):
            cues = [{"name": cues, "at": sc.get("sfx_at", 5)}]
        for cue in cues[:3]:
            try:
                at = min(max(float(cue.get("at", 5)), 0.3), cd - 0.4) * stretch
            except Exception:
                at = 5.0
            if at < seg_len - 0.3:
                sfx.append((t + at, sfx_file(cue.get("name")), 0.55))
        t += seg_len
    T = round(t, 3)
    if s.get("hook_text") and os.environ.get("HOOK_TEXT"):
        sfx.append((0.0, sfx_file("pop"), 0.5))
        events.append((0.0, 2.2, "Hook", "{\\fscx130\\fscy130\\t(0,150,\\fscx100\\fscy100)}" + s["hook_text"].upper()))
    ass = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Word,{FONT},66,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,6,2,2,90,90,700,1
Style: Hook,{FONT},120,&H0000E5FF,&H00FFFFFF,&H00000000,&H90000000,0,0,0,0,100,100,2,0,1,12,6,8,60,60,230,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" + "\n".join(f"Dialogue: 0,{ts(a)},{ts(b)},{st_},,0,0,0,,{x}" for a, b, st_, x in sorted(events)) + "\n"
    (work / "captions.ass").write_text(ass, encoding="utf-8")

    # audio mix: narration on top, sfx, music ducked under speech
    inputs, af, mix = [], [], []
    k = 0
    for st, mp3, tempo, sd in speech:
        ms = int(st * 1000); inputs += ["-i", mp3]
        af.append(f"[{k}:a]asetrate={EDGE_SR * SHIFT:.0f},aresample=48000,atempo={tempo / SHIFT:.4f},acompressor=threshold=-18dB:ratio=3:attack=5:release=80:makeup=2,aformat=channel_layouts=stereo,volume=1.5,adelay={ms}|{ms},apad=whole_dur={T}[a{k}]")
        mix.append(f"[a{k}]"); k += 1
    sfx = [] if os.environ.get("SFX", "0") != "1" else sfx   # user wants music only, no sound effects
    for st, f, g in sfx:
        ms = int(st * 1000); inputs += ["-i", f]
        af.append(f"[{k}:a]aresample=48000,aformat=channel_layouts=stereo,volume={g},adelay={ms}|{ms},apad=whole_dur={T}[a{k}]")
        mix.append(f"[a{k}]"); k += 1
    md = D / "assets" / "music"
    moods = json.loads((md / "moods.json").read_text(encoding="utf-8")) if (md / "moods.json").exists() else {}
    pick = moods.get(str(s.get("music_mood", "")).lower()) or [p.stem for p in md.glob("*.mp3")]
    music = [md / f"{n}.mp3" for n in pick if (md / f"{n}.mp3").exists()]
    if music:
        inputs += ["-stream_loop", "-1", "-i", random.choice(music)]
        duck = "+".join(f"between(t,{a - 0.05:.2f},{a + d + 0.1:.2f})" for a, _, _, d in speech) or "0"
        af.append(f"[{k}:a]atrim=0:{T},asetpts=N/SR/TB,aresample=48000,aformat=channel_layouts=stereo,"
                  f"volume='if({duck},0.17,0.34)':eval=frame,afade=t=in:d=0.5,afade=t=out:st={T - 1}:d=1,apad=whole_dur={T}[a{k}]")
        mix.append(f"[a{k}]"); k += 1
    af.append("".join(mix) + f"amix=inputs={len(mix)}:duration=longest:normalize=0,asetpts=N/SR/TB,atrim=duration={T},"
              "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[aout]")
    (work / "agraph.txt").write_text(";".join(af), encoding="utf-8")
    sh(FF, "-v", "error", "-y", *inputs, "-filter_complex_script", work / "agraph.txt", "-map", "[aout]", "-t", T, work / "mix.wav")

    # video: each clip -> 1080x1920, small punch-in zoom at the start of each scene, concat, captions
    vin, vf = [], []
    for i, (clip, cd, stretch) in enumerate(segs):
        vin += ["-i", clip]
        L = cd * stretch
        z = "1.0+0.04*t/" + f"{L:.2f}"                 # slow push-in, no punch (story pacing)
        vf.append(f"[{i}:v]trim=0:{cd:.3f},setpts=(PTS-STARTPTS)*{stretch:.4f},fps=30,"
                  f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
                  f"scale=w='1080*({z})':h='1920*({z})':eval=frame,crop=1080:1920,setsar=1,trim=0:{L:.3f}[v{i}]")
    fonts = os.environ.get("FONTS_DIR", str(D / "assets" / "fonts")).replace("\\", "/").replace(":", "\\:")
    subs = str(work / "captions.ass").replace("\\", "/").replace(":", "\\:")
    vf.append("".join(f"[v{i}]" for i in range(len(segs))) + f"concat=n={len(segs)}:v=1:a=0,"
              f"subtitles='{subs}':fontsdir='{fonts}',format=yuv420p[vout]")
    (work / "vgraph.txt").write_text(";".join(vf), encoding="utf-8")
    final = work / "final.mp4"
    sh(FF, "-v", "error", "-y", *vin, "-i", work / "mix.wav", "-filter_complex_script", work / "vgraph.txt",
       "-map", "[vout]", "-map", f"{len(segs)}:a", "-t", T, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
       "-r", "30", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", final)
    sh(FF, "-v", "error", "-i", final, "-f", "null", "-")
    print("final", final, dur(final))
    return final, T


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--script"); ap.add_argument("--clips"); ap.add_argument("--no-upload", action="store_true")
    a = ap.parse_args()
    STATE.mkdir(exist_ok=True)
    hist = jload(STATE / "history.json", [])
    formats = jload(STATE / "formats.json", [])
    stamp = dt.datetime.utcnow().strftime("%Y%m%d-%H%M")
    work = D / "work" / stamp
    work.mkdir(parents=True, exist_ok=True)
    result = {"t": time.time(), "stamp": stamp}
    try:
        if not a.no_upload:
            refresh_stats(hist)
            if drain_queue(hist):
                result["note"] = "uploaded/limited from queue, no new episode this run"
                print(result["note"]); return
        if a.script:
            s = jload(a.script, None); fmt = {"id": s.get("format", "test")}; why = "manual"
        else:
            fmt, why = pick_format(formats, hist)
            forced = [f for f in formats if f["id"] == os.environ.get("FORCE_FORMAT", "").strip()]
            if forced:
                fmt, why = forced[0], "forced"
            if fmt is None:
                fmt = invent_format(formats, hist); formats.append(fmt)
            s = write_script(fmt, hist)
        s["format"] = fmt["id"]; result.update(format=fmt["id"], why=why, title=s["title"])
        print("format", fmt["id"], why, "|", s["title"])
        (work / "script.json").write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
        if a.clips:
            clips = [Path(a.clips) / f"clip{i + 1}.mp4" for i in range(5)]
        else:
            prompts = [video_prompt(sc, s.get("characters")) for sc in s["scenes"]]
            (work / "prompts.json").write_text(json.dumps(prompts), encoding="utf-8")
            subprocess.run(["node.exe" if os.name == "nt" else "node", str(D / "gen_meta.mjs"), str(work / "prompts.json"), str(work / "clips")], check=False)
            clips = [work / "clips" / f"clip{i + 1}.mp4" for i in range(len(prompts))]
            miss = [i for i, c in enumerate(clips) if not (c.exists() and dur(c) > 3)]
            if miss and len(miss) <= len(prompts) // 2:          # one retry pass for the scenes that failed
                (work / "retry.json").write_text(json.dumps([prompts[i] for i in miss]), encoding="utf-8")
                subprocess.run(["node.exe" if os.name == "nt" else "node", str(D / "gen_meta.mjs"), str(work / "retry.json"), str(work / "clips_retry")], check=False)
                for k, i in enumerate(miss):
                    r = work / "clips_retry" / f"clip{k + 1}.mp4"
                    if r.exists():
                        shutil.copy(r, clips[i])
        n = len(s["scenes"])
        if a.clips:
            clips = [Path(a.clips) / f"clip{i + 1}.mp4" for i in range(n)]
        clips = [c if c.exists() and dur(c) > 3 else None for c in clips]
        got = sum(c is not None for c in clips); result["clips"] = got
        if got < max(5, n - 2) or clips[0] is None or clips[-1] is None:
            raise RuntimeError(f"only {got}/{n} clips")
        for i, c in enumerate(clips):                            # a missing middle scene reuses its neighbour's footage
            if c is None:
                clips[i] = clips[i - 1] or clips[i + 1]
        final, T = assemble(s, clips, work)
        result["dur"] = T
        if not a.no_upload:
            try:
                vid = upload(final, s)
            except UploadLimit:
                enqueue(final, s, why, stamp); result["note"] = "upload limit: queued"; print(result["note"]); return
            result.update(id=vid, url=f"https://youtube.com/shorts/{vid}")
            print("UPLOADED", result["url"])
            hist.append({"id": vid, "t": time.time(), "format": fmt["id"], "title": s["title"], "why": why})
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"; print("ERROR", result["error"])
    finally:
        (STATE / "history.json").write_text(json.dumps(hist[-500:], ensure_ascii=False, indent=1), encoding="utf-8")
        (STATE / "formats.json").write_text(json.dumps(formats, ensure_ascii=False, indent=1), encoding="utf-8")
        with open(STATE / "runs.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
    if result.get("error"):
        sys.exit(1)


if __name__ == "__main__":
    main()
