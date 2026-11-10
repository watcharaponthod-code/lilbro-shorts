// Ask meta.ai (text chat) and print the JSON object from its reply.
// usage: node ask_meta.mjs prompt.txt out.json      env: META_COOKIES or META_COOKIES_FILE
import fs from "node:fs";
import puppeteer from "puppeteer-core";

const [, , promptFile, outFile] = process.argv;
const prompt = fs.readFileSync(promptFile, "utf8").trim();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const CHROME = process.env.CHROME || ["/usr/bin/google-chrome", "/usr/bin/chromium-browser",
  "C:/Program Files/Google/Chrome/Application/chrome.exe"].find((p) => fs.existsSync(p));

function lastJson(t) {
  // scan from the end for a balanced {...} that parses
  for (let e = t.lastIndexOf("}"); e > 0; e = t.lastIndexOf("}", e - 1)) {
    let depth = 0;
    for (let s = e; s >= 0; s--) {
      if (t[s] === "}") depth++;
      else if (t[s] === "{" && --depth === 0) {
        try { return JSON.parse(t.slice(s, e + 1)); } catch (_) { break; }
      }
    }
  }
  return null;
}

const b = await puppeteer.launch({ executablePath: CHROME, headless: process.env.HEADLESS === "0" ? false : "new",
  args: ["--no-sandbox", "--disable-dev-shm-usage", "--window-size=1280,900", "--lang=en-US"] });
try {
  const ck = JSON.parse(process.env.META_COOKIES || fs.readFileSync(process.env.META_COOKIES_FILE, "utf8"));
  await b.setCookie(...ck.map((c) => ({ name: c.name, value: c.value, domain: c.domain, path: c.path || "/",
    secure: !!c.secure, httpOnly: !!c.httpOnly, sameSite: c.sameSite, expires: c.expires > 0 ? c.expires : undefined })));
  const p = await b.newPage();
  await p.setViewport({ width: 1280, height: 900 });
  await p.goto("https://www.meta.ai/", { waitUntil: "domcontentloaded", timeout: 90000 }).catch(() => {});
  await p.waitForSelector("[contenteditable=true]", { timeout: 30000 }).catch(() => null); await sleep(2500);
  for (let i = 0; i < 3 && !(await p.$("[contenteditable=true]")); i++) { await p.reload().catch(() => {}); await sleep(6000); }
  if (!(await p.$("[contenteditable=true]"))) throw new Error("composer not found (cookies expired?)");
  await p.click("[contenteditable=true]");
  // single line: newlines would send early
  await p.keyboard.sendCharacter(prompt.replace(/\s*\n\s*/g, " "));
  await sleep(1200);
  const send = await p.$("[aria-label=Send]");
  if (send) await send.click(); else await p.keyboard.press("Enter");
  const marker = prompt.replace(/\s+/g, " ").slice(-60);
  let prev = "", stable = 0, obj = null;
  for (let i = 0; i < 90; i++) {
    await sleep(2000);
    const t = await p.evaluate(() => document.body.innerText);
    const k = t.replace(/\s+/g, " ").lastIndexOf(marker);
    const reply = k >= 0 ? t.replace(/\s+/g, " ").slice(k + marker.length) : "";
    if (reply && reply === prev) stable++; else stable = 0;
    prev = reply;
    obj = lastJson(reply);
    if (obj && stable >= 3) break;
  }
  if (!obj) { fs.writeFileSync(outFile + ".txt", prev); throw new Error("no JSON in meta reply"); }
  fs.writeFileSync(outFile, JSON.stringify(obj, null, 1));
  console.log("ok", Object.keys(obj).join(","));
} finally { await b.close().catch(() => {}); }
