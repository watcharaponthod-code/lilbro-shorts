// Generate cover images on meta.ai (one chat per prompt, in parallel) and download the first image of each.
// usage: node gen_cover.mjs prompts.json outdir      env: META_COOKIES or META_COOKIES_FILE
import fs from "node:fs";
import path from "node:path";
import puppeteer from "puppeteer-core";

const [, , pf, outDir] = process.argv;
const prompts = JSON.parse(fs.readFileSync(pf, "utf8"));
fs.mkdirSync(outDir, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);
const CHROME = process.env.CHROME || ["/usr/bin/google-chrome", "/usr/bin/chromium-browser",
  "C:/Program Files/Google/Chrome/Application/chrome.exe"].find((p) => fs.existsSync(p));
let lock = Promise.resolve();
const exclusive = (fn) => { const r = lock.then(fn, fn); lock = r.catch(() => {}); return r; };

async function one(b, i, text) {
  const p = await b.newPage();
  await p.setViewport({ width: 1280, height: 900 });
  await exclusive(async () => { await p.bringToFront().catch(() => {});
    await p.goto("https://www.meta.ai/", { waitUntil: "domcontentloaded", timeout: 90000 }).catch(() => {});
    if (!(await p.waitForSelector("[contenteditable=true]", { timeout: 40000 }).catch(() => null))) throw new Error("composer not found");
    await sleep(2500);
    await p.click("[contenteditable=true]");
    await p.keyboard.sendCharacter(text.replace(/\s*\n\s*/g, " "));
    await sleep(1200);
    const s = await p.$("[aria-label=Send]"); if (s) await s.click(); else await p.keyboard.press("Enter");
    await sleep(3000);
  });
  log(`cover ${i} sent`);
  for (let k = 0; k < 40; k++) {
    await sleep(5000);
    const src = await exclusive(async () => {
      await p.bringToFront().catch(() => {}); await sleep(1500);
      return p.evaluate(() => {
        const im = [...document.querySelectorAll("img")].filter((m) => m.naturalWidth >= 500 && /fbcdn|meta|scontent/.test(m.src));
        return im.length ? im[0].src : null;
      });
    });
    if (src) {
      await sleep(6000);   // let the full-res version load
      const best = await p.evaluate(() => {
        const im = [...document.querySelectorAll("img")].filter((m) => m.naturalWidth >= 500 && /fbcdn|meta|scontent/.test(m.src));
        im.sort((a, b) => b.naturalWidth * b.naturalHeight - a.naturalWidth * a.naturalHeight);
        return im.map((m) => m.src);
      });
      for (const [j, u] of best.slice(0, 4).entries()) {
        const buf = Buffer.from(await (await fetch(u)).arrayBuffer());
        fs.writeFileSync(path.join(outDir, `cover${i}_${j}.jpg`), buf);
      }
      log(`cover ${i} saved ${Math.min(best.length, 4)} images`);
      return true;
    }
  }
  return false;
}

const b = await puppeteer.launch({ executablePath: CHROME, headless: process.env.HEADLESS === "0" ? false : "new",
  args: ["--no-sandbox", "--disable-dev-shm-usage", "--window-size=1280,900", "--lang=en-US",
    "--disable-background-timer-throttling", "--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding"] });
try {
  const ck = JSON.parse(process.env.META_COOKIES || fs.readFileSync(process.env.META_COOKIES_FILE, "utf8"));
  await b.setCookie(...ck.map((c) => ({ name: c.name, value: c.value, domain: c.domain, path: c.path || "/",
    secure: !!c.secure, httpOnly: !!c.httpOnly, sameSite: c.sameSite, expires: c.expires > 0 ? c.expires : undefined })));
  const ok = await Promise.all(prompts.map((t, i) => one(b, i + 1, t).catch((e) => { log(String(e)); return false; })));
  log("done", ok);
} finally { await b.close().catch(() => {}); }
