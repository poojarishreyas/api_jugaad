require('dotenv').config();

module.exports = {
  // ── Generic config ───────────────────────────────────────────
  provider: (process.env.PROVIDER || 'chatgpt').toLowerCase(),
  port: process.env.PORT || 3000,
  apiKey: process.env.API_KEY || null,

  // ── ChatGPT tokens ──────────────────────────────────────────
  sessionToken0: process.env.SESSION_TOKEN_0,
  sessionToken1: process.env.SESSION_TOKEN_1,

  // ── Z.ai tokens ─────────────────────────────────────────────
  // ZAI_COOKIES: all cookies as JSON string (most reliable)
  // e.g. ZAI_COOKIES=[{"name":"oauth_id_token","value":"...","name":"acw_tc","value":"..."}]
  zaiCookies: process.env.ZAI_COOKIES || null,
  zaiSessionCookie: process.env.ZAI_SESSION_COOKIE,

  // ── Gemini tokens ───────────────────────────────────────────
  geminiPSID: process.env.GEMINI_PSID,
  geminiPSIDTS: process.env.GEMINI_PSIDTS,
  geminiPSIDCC: process.env.GEMINI_PSIDCC,
};
