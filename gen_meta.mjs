// Generate N 10-second clips on meta.ai in parallel tabs, download them.
// usage: node gen_meta.mjs scenes.json outdir
// env: META_COOKIES (JSON array of cookies), CHROME (optional executable path), HEADLESS=0 to watch
import fs from "node:fs";
import path from "node:path";
import puppeteer from "puppeteer-core";

const [, , scenesFile, outDir] = process.argv;
const scenes = JSON.parse(fs.readFileSync(scenesFile, "utf8"));
fs.mkdirSync(outDir, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);
const CHROME = process.env.CHROME || ["/usr/bin/google-chrome", "/usr/bin/chromium-browser",
  "C:/Program Files/Google/Chrome/Application/chrome.exe"].find((p) => fs.existsSync(p));
const DEADLINE = Date.now() + (+process.env.META_MAX_MIN || 16) * 60e3;

async function setInstant(p) {
  const pill = await p.$$eval("button,[role=button]", (bs) => {
    const b = bs.find((b) => /^(Thinking|Instant)/.test(b.innerText.trim()) && b.getBoundingClientRect().width);
    if (!b) return null; const q = b.getBoundingClientRect(); return [b.innerText.trim(), q.x + q.width / 2, q.y + q.height / 2];
  });
  if (!pill || pill[0].startsWith("Instant")) return pill ? pill[0] : "none";
  await p.mouse.click(pill[1], pill[2]); await sleep(1200);
  const it = await p.evaluate(() => {
    const e = [...document.querySelectorAll("div,span,p")].find((e) => e.childElementCount == 0 &&
      (e.innerText || "").trim() == "Instant" && e.getBoundingClientRect().height);
    if (!e) return null; const q = e.getBoundingClientRect(); return [q.x + q.width / 2, q.y + q.height / 2];
  });
  if (it) { await p.mouse.click(it[0], it[1]); await sleep(1000); }
  return "Instant(set)";
}

async function videos(p) {
  return p.evaluate(() => [...document.querySelectorAll("video")]
    .map((v) => v.currentSrc || v.src).filter((s) => s && s.startsWith("http")));
}

async function submit(b, i, text) {
  const p = await b.newPage();
  await p.setViewport({ width: 1280, height: 900 });
  for (let a = 0; a < 3; a++) {
    await p.goto("https://www.meta.ai/", { waitUntil: "networkidle2", timeout: 90000 }).catch(() => {});
    await sleep(4000);
    if (await p.$("[contenteditable=true]")) break;
  }
  if (!(await p.$("[contenteditable=true]"))) {
    fs.writeFileSync(path.join(outDir, `fail_${i}.html`), await p.content());
    throw new Error(`scene ${i}: composer not found (cookies expired / login wall?) url=${p.url()}`);
  }
  log(`scene ${i} mode`, await setInstant(p));
  await p.click("[contenteditable=true]");
  await p.keyboard.sendCharacter(text);
  await sleep(1500);
  const send = await p.$("[aria-label=Send]");
  if (send) await send.click(); else await p.keyboard.press("Enter");
  for (let k = 0; k < 40 && !p.url().includes("/prompt/"); k++) await sleep(1500);
  log(`scene ${i} submitted`, p.url());
  return p;
}

async function collect(p, i) {
  const chat = p.url();
  let n = 0;
  while (Date.now() < DEADLINE) {
    await sleep(15000); n++;
    let v = await videos(p);
    if (!v.length && n % 4 == 0) {          // finished videos sometimes only appear after a refresh
      await p.goto(chat, { waitUntil: "networkidle2", timeout: 60000 }).catch(() => {});
      await sleep(6000); v = await videos(p);
    }
    const txt = await p.evaluate(() => document.body.innerText.slice(-600)).catch(() => "");
    if (/limit|try again later|can't create|unable to/i.test(txt) && !v.length && n > 4) log(`scene ${i} page says:`, txt.slice(-200).replace(/\s+/g, " "));
    if (v.length) {
      const src = v[v.length - 1];
      const r = await fetch(src);
      const buf = Buffer.from(await r.arrayBuffer());
      if (buf.length > 50000) {
        fs.writeFileSync(path.join(outDir, `clip${i}.mp4`), buf);
        log(`scene ${i} downloaded ${(buf.length / 1e6).toFixed(1)}MB`);
        return true;
      }
    }
  }
  log(`scene ${i} timed out`, chat);
  return false;
}

const b = await puppeteer.launch({
  executablePath: CHROME, headless: process.env.HEADLESS === "0" ? false : "new",
  args: ["--no-sandbox", "--disable-dev-shm-usage", "--window-size=1280,900", "--lang=en-US"],
});
try {
  const ck = JSON.parse(process.env.META_COOKIES || fs.readFileSync(process.env.META_COOKIES_FILE, "utf8"));
  await b.setCookie(...ck.map((c) => ({ name: c.name, value: c.value, domain: c.domain, path: c.path || "/",
    secure: !!c.secure, httpOnly: !!c.httpOnly, sameSite: c.sameSite, expires: c.expires > 0 ? c.expires : undefined })));
  const pages = [];
  for (let i = 0; i < scenes.length; i++) {          // stagger submits a little; meta rate-limits bursts
    try { pages.push(await submit(b, i + 1, scenes[i])); } catch (e) { log(String(e)); pages.push(null); }
    await sleep(3000);
  }
  const ok = await Promise.all(pages.map((p, i) => (p ? collect(p, i + 1) : false)));
  fs.writeFileSync(path.join(outDir, "gen_result.json"), JSON.stringify({ ok, chats: pages.map((p) => p && p.url()) }));
  log("done", ok);
} finally { await b.close().catch(() => {}); }
