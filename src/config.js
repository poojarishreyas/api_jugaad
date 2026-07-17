require('dotenv').config();

const config = {
  // ── Generic config ───────────────────────────────────────────
  provider: (process.env.PROVIDER || 'chatgpt').toLowerCase(),
  port: process.env.PORT || 3000,
  apiKey: process.env.API_KEY || null,
  chromeUserDataDir: process.env.CHROME_USER_DATA_DIR || null,
  chromeExecutablePath: process.env.CHROME_EXECUTABLE_PATH || null,

  // ── ChatGPT tokens ──────────────────────────────────────────
  sessionToken0: process.env.SESSION_TOKEN_0,
  sessionToken1: process.env.SESSION_TOKEN_1,

  // ── Z.ai tokens ─────────────────────────────────────────────
  zaiCookies: process.env.ZAI_COOKIES || null,
  zaiSessionCookie: process.env.ZAI_SESSION_COOKIE,

  // ── Gemini tokens ───────────────────────────────────────────
  geminiPSID: process.env.GEMINI_PSID,
  geminiPSIDTS: process.env.GEMINI_PSIDTS,
  geminiPSIDCC: process.env.GEMINI_PSIDCC,
  
  reload: function() {
    require('dotenv').config({ override: true });
    this.provider = (process.env.PROVIDER || 'chatgpt').toLowerCase();
    this.port = process.env.PORT || 3000;
    this.apiKey = process.env.API_KEY || null;
    this.chromeUserDataDir = process.env.CHROME_USER_DATA_DIR || null;
    this.chromeExecutablePath = process.env.CHROME_EXECUTABLE_PATH || null;
    this.sessionToken0 = process.env.SESSION_TOKEN_0;
    this.sessionToken1 = process.env.SESSION_TOKEN_1;
    this.zaiCookies = process.env.ZAI_COOKIES || null;
    this.zaiSessionCookie = process.env.ZAI_SESSION_COOKIE;
    this.geminiPSID = process.env.GEMINI_PSID;
    this.geminiPSIDTS = process.env.GEMINI_PSIDTS;
    this.geminiPSIDCC = process.env.GEMINI_PSIDCC;
  }
};

module.exports = config;
