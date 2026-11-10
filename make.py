"""One ~55s Roblox 2D cartoon Short per run: pick a format (test & learn), write an HPC script, make 5 meta.ai
clips, Microsoft Edge voice-over + word captions + SFX + music, upload to YouTube through Maton, log for learning.

Run (Actions):  python make.py            env: GITHUB_TOKEN (models), META_COOKIES, MATON_API_KEY, MATON_YT_MONKEY_CONNECTION
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
VOICE, RATE, PITCH = os.environ.get("VOICE", "en-US-AndrewMultilingualNeural"), "+12%", "+0Hz"
CHANNEL_ID = "UCczRwdCgEiEsXG-6Ji2mWew"  # Lil Bro Chaos (monkey connection); abort if Maton points elsewhere
GW = "https://gateway.maton.ai/youtube"
FONT = os.environ.get("FONT_NAME", "Luckiest Guy")

STYLE = ("Modern 2D TV cartoon style (no channel logos, no watermark): thick uniform black outlines, flat bright cel "
         "colors, smooth hand-animated motion, soft painted background. All characters are ROBLOX avatars drawn as 2D "
         "cartoons: blocky square heads, blocky rectangular bodies and limbs, simple Roblox faces.")
CAST = {
    "Noob": "Noob: the classic Roblox noob, yellow blocky head with a simple black smile, bright blue blocky torso, green blocky legs, yellow arms",
    "Bacon": "Bacon: Roblox boy with brown 'bacon hair', default smile, plain black t-shirt, blue jeans",
    "Guest": "Guest: Roblox guest avatar, black baseball cap with white G, white t-shirt, dark blue pants",
    "Pro": "Pro: cool Roblox pro player, spiky purple hair, black hoodie, sunglasses, glowing sword",
    "Hacker": "Hacker: Roblox hacker, black hood over a dark face with glowing red eyes, green code on his shirt",
    "Mom": "Mom: Roblox mom avatar, long brown hair, pink sweater, angry eyebrows when mad",
    "Admin": "Admin: giant Roblox admin, golden crown, red cape, glowing white eyes, holds a ban hammer",
}
SFX_FILES = ["vineboom", "bruh", "badgas1", "phonejingle", "mentality", "whoosh", "pop", "ding", "boom", "riser"]
CHAN_RULES = """Audience: kids and young teens (8-16) who play Roblox and scroll Shorts.
HPC formula (from a creator with 3M-9M view shorts):
- HOOK (scene 1, first 5 s): fast, introduces the topic but leaves big questions open; first spoken line names the situation in <= 9 words.
- PROGRESSION (scenes 2-4): deliver exactly what the hook promised, escalate each scene, small jokes, no early payoff.
- CLIMAX (scene 5): the payoff/twist the viewer waited for, happens only at the very end. End on a punchline that makes people rewatch.
Never reveal the answer early. Every scene must show clear ACTION (movement, chase, fall, explosion, transformation), not talking heads."""


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
                if r.status_code != 200:
                    last = f"{model} {r.status_code} {r.text[:200]}"; break
                txt = r.json()["choices"][0]["message"]["content"]
                return json.loads(txt[txt.index("{"): txt.rindex("}") + 1])
            except Exception as e:
                last = f"{model} {e}"; time.sleep(3)
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
    meta = {"snippet": {"title": s["title"][:100], "description": s["description"][:4900], "tags": s["tags"][:20],
                        "categoryId": "1", "defaultLanguage": "en", "defaultAudioLanguage": "en"},
            "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False, "containsSyntheticMedia": False}}
    ch = requests.get(f"{GW}/youtube/v3/channels", params={"part": "id", "mine": "true"}, headers=maton_h(), timeout=60).json()
    cid = (ch.get("items") or [{}])[0].get("id")
    if cid != CHANNEL_ID:
        raise SystemExit(f"wrong channel {cid}, refusing to upload")
    bd = "mtn" + os.urandom(12).hex()
    body = (f"--{bd}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{json.dumps(meta)}\r\n--{bd}\r\n"
            f"Content-Type: video/mp4\r\n\r\n").encode() + Path(final).read_bytes() + f"\r\n--{bd}--\r\n".encode()
    r = requests.post(f"{GW}/upload/youtube/v3/videos?uploadType=multipart&part=snippet,status", data=body, timeout=600,
                      headers={**maton_h(), "Content-Type": f"multipart/related; boundary={bd}"})
    j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if not j.get("id"):
        raise SystemExit(f"upload failed {r.status_code} {r.text[:400]}")
    return j["id"]


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
    if untried and r < 0.6:
        return random.choice(untried), "explore-untried"
    if r < 0.2 or not stats:
        return None, "invent"            # caller invents a brand-new format
    best = max((f for f in active if f["id"] in stats and not f.get("retired")),
               key=lambda f: np.mean(sorted(stats[f["id"]])[-5:]), default=None)
    return (best, "exploit") if best else (random.choice(active), "random")


def invent_format(formats, hist):
    top = sorted([h for h in hist if h.get("views") is not None], key=lambda h: -h["views"])[:5]
    j = llm_json(f"""You run a YouTube Shorts channel of 2D cartoon ROBLOX animations for kids. {CHAN_RULES}
Existing formats (id: idea): {json.dumps({f['id']: f['idea'] for f in formats})}
Our best videos so far: {json.dumps([{k: h.get(k) for k in ('title', 'format', 'views', 'age_min')} for h in top])}
Invent ONE new short format that is different from the existing ones, proven on Shorts for this audience in 2025-2026
(think: trending Roblox games like Steal a Brainrot, 99 Nights in the Forest, Grow a Garden, Escape Tsunami, Doors;
'POV', 'Noob vs Pro vs Hacker', '1% vs 1000%', relatable school/family moments, satisfying transformations, survival).
Return JSON {{"id": "snake_case_id", "idea": "one sentence format description", "title_pattern": "e.g. Noob vs Pro vs Hacker: ___ 💀"}}""")
    j["id"] = re.sub(r"[^a-z0-9_]", "", j["id"].lower())[:40] or f"fmt{len(formats)}"
    j["invented"] = dt.datetime.utcnow().isoformat()[:16]
    return j


def write_script(fmt, hist):
    recent = [h["title"] for h in hist[-30:]]
    cast_txt = "\n".join(CAST.values())
    j = llm_json(f"""Write a 55-second YouTube Short: a 2D cartoon ROBLOX animation. Format: {fmt['idea']} Title pattern: {fmt.get('title_pattern', '')}
{CHAN_RULES}
Recurring cast you may use (pick 2-3, keep their looks exactly): {cast_txt}
It is told by a fast, funny NARRATOR voice-over (the characters do not lip-sync), like a kid storyteller roasting what happens.
Exactly 5 scenes, each ~10-11 seconds of video:
- "video": a vivid description of what HAPPENS on screen in this 10 s: who, where, the action in order, with 3 hard camera cuts
  written as [0-3s] ... [3-6s] ... [6-10s] .... Visual only: no on-screen text, no speech bubbles. Mention each character's look in short.
- "say": the narrator line for this scene, 20-26 words, punchy, present tense, simple words a 10-year-old gets. Scene 1 starts with the hook.
- "sfx": one of {SFX_FILES} that fits the key moment of this scene, and "sfx_at": seconds into the scene (0-10) when it hits.
- "keywords": 1-3 words from "say" to highlight in yellow.
Do NOT repeat these recent titles/ideas: {json.dumps(recent)}
Return JSON: {{"title": "max 60 chars, ends with 💀, never the word AI", "hook_text": "3-5 word on-screen hook for the first 2 s",
"description": "2 lines: a hook sentence + a question for viewers, then 6 hashtags incl #shorts #roblox #robloxanimation",
"tags": ["15 search tags"], "scenes": [{{"video": "...", "say": "...", "sfx": "...", "sfx_at": 4.0, "keywords": ["..."]}}]}}""")
    assert len(j["scenes"]) >= 5, "need 5 scenes"
    j["scenes"] = j["scenes"][:5]
    j["title"] = re.sub(r"\bAI\b", "", j["title"]).strip()
    return j


def video_prompt(sc):
    return (f"Create a 10-second vertical 9:16 video. {STYLE} {sc['video']} Fast, smooth, energetic animation with lots of "
            f"movement and the 3 camera cuts. No text, no captions, no speech bubbles. AUDIO: no dialogue, no music.")


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


def tts(text, out):
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
    sfxd = work / "sfx"; sfxd.mkdir(exist_ok=True)
    for f in (D / "assets" / "sfx").glob("*.wav"):
        shutil.copy(f, sfxd / f.name)
    synth_sfx(sfxd)
    segs, events, speech, sfx, t = [], [], [], [], 0.0
    for i, (sc, clip) in enumerate(zip(s["scenes"], clips)):
        if clip is None:
            continue
        cd = min(dur(clip), 11.0)
        mp3 = work / f"vo{i}.mp3"; W = tts(sc["say"], mp3); vd = dur(mp3)
        tempo = min(1.3, max(1.0, vd / (cd - 0.5)))
        sd = vd / tempo
        stretch = max(1.0, (sd + 0.5) / cd)          # slow the clip a bit if the line still runs long
        seg_len = cd * stretch
        segs.append((clip, cd, stretch))
        st = t + 0.15
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
            if len(cur) == 3 or wd["w"][-1] in ".,!?" or (len(cur) == 2 and len(wd["w"]) > 6):
                chunks.append(cur); cur = []
        if cur: chunks.append(cur)
        for k, ch in enumerate(chunks):
            s0 = st + ch[0]["s"] / tempo
            e0 = st + (chunks[k + 1][0]["s"] / tempo if k + 1 < len(chunks) else ch[-1]["e"] / tempo + 0.3)
            txt = " ".join(("{\\c&H00E5FF&}" + x["w"].upper() + "{\\c&HFFFFFF&}") if x["w"].upper().strip(".,!?") in keys
                           else x["w"].upper() for x in ch)
            events.append((s0, e0, "Word", "{\\fscx118\\fscy118\\t(0,90,\\fscx100\\fscy100)}" + txt))
        if i > 0:
            sfx.append((max(0, t - 0.2), "whoosh", 0.35))
        name = sc.get("sfx") if sc.get("sfx") in SFX_FILES else "pop"
        sfx.append((t + min(max(float(sc.get("sfx_at", 5)), 0.5), cd - 0.5) * stretch, name, 0.8))
        t += seg_len
    T = round(t, 3)
    if s.get("hook_text"):
        events.append((0.0, 2.2, "Hook", "{\\fscx130\\fscy130\\t(0,150,\\fscx100\\fscy100)}" + s["hook_text"].upper()))
    ass = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Word,{FONT},104,&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,0,0,0,0,100,100,2,0,1,10,5,2,60,60,520,1
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
        af.append(f"[{k}:a]atempo={tempo:.4f},aresample=48000,aformat=channel_layouts=stereo,volume=1.8,adelay={ms}|{ms},apad=whole_dur={T}[a{k}]")
        mix.append(f"[a{k}]"); k += 1
    for st, name, g in sfx:
        ms = int(st * 1000); inputs += ["-i", sfxd / f"{name}.wav"]
        af.append(f"[{k}:a]aresample=48000,aformat=channel_layouts=stereo,volume={g},adelay={ms}|{ms},apad=whole_dur={T}[a{k}]")
        mix.append(f"[a{k}]"); k += 1
    music = sorted((D / "assets" / "music").glob("*.mp3"))
    if music:
        inputs += ["-stream_loop", "-1", "-i", random.choice(music)]
        duck = "+".join(f"between(t,{a - 0.05:.2f},{a + d + 0.1:.2f})" for a, _, _, d in speech) or "0"
        af.append(f"[{k}:a]atrim=0:{T},asetpts=N/SR/TB,aresample=48000,aformat=channel_layouts=stereo,"
                  f"volume='if({duck},0.07,0.22)':eval=frame,afade=t=in:d=0.5,afade=t=out:st={T - 1}:d=1,apad=whole_dur={T}[a{k}]")
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
        z = "1.08-0.08*min(t/0.35,1)"
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
        if a.script:
            s = jload(a.script, None); fmt = {"id": s.get("format", "test")}; why = "manual"
        else:
            fmt, why = pick_format(formats, hist)
            if fmt is None:
                fmt = invent_format(formats, hist); formats.append(fmt)
            s = write_script(fmt, hist)
        s["format"] = fmt["id"]; result.update(format=fmt["id"], why=why, title=s["title"])
        print("format", fmt["id"], why, "|", s["title"])
        (work / "script.json").write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
        if a.clips:
            clips = [Path(a.clips) / f"clip{i + 1}.mp4" for i in range(5)]
        else:
            (work / "prompts.json").write_text(json.dumps([video_prompt(sc) for sc in s["scenes"]]), encoding="utf-8")
            subprocess.run(["node", str(D / "gen_meta.mjs"), str(work / "prompts.json"), str(work / "clips")], check=False)
            clips = [work / "clips" / f"clip{i + 1}.mp4" for i in range(5)]
        clips = [c if c.exists() and dur(c) > 3 else None for c in clips]
        got = sum(c is not None for c in clips); result["clips"] = got
        if got < 4 or clips[-1] is None:
            raise RuntimeError(f"only {got}/5 clips (need 4+ incl. the climax)")
        final, T = assemble(s, clips, work)
        result["dur"] = T
        if not a.no_upload:
            vid = upload(final, s)
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
