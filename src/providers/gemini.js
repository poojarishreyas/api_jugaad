/**
 * Google Gemini Provider
 *
 * Drives the gemini.google.com web UI via Puppeteer.
 * Auth: Google session cookies (__Secure-1PSID, __Secure-1PSIDTS, etc.)
 *
 * NOTE: Google aggressively detects headless browsers. The stealth plugin
 * helps but is not guaranteed. If you get blocked, try:
 *   1. Running with headless: false (headed mode) to solve CAPTCHAs
 *   2. Using a fresh Chrome profile
 *   3. Reducing request frequency
 *
 * To inspect/update selectors:
 *   1. Open gemini.google.com in your browser
 *   2. Open DevTools (F12) → Elements
 *   3. Locate the input field, send button, and response containers
 *   4. Update the SELECTORS object below
 */
const config = require('../config');

// ── Gemini DOM selectors ───────────────────────────────────────
// Update these after inspecting the live Gemini web UI in DevTools.
const SELECTORS = {
  inputBox: 'div.ql-editor[contenteditable="true"], rich-textarea div[contenteditable="true"], div[aria-label*="prompt"], textarea[aria-label*="prompt"]',
  sendButton: 'button[aria-label="Send message"], button.send-button, button[data-test-id="send-button"], button[mattooltip="Send"]',
  stopButton: 'button[aria-label="Stop responding"], button[aria-label="Stop"], button[mattooltip="Stop responding"]',
  responseContainer: 'message-content, .response-container, .model-response-text, div[class*="response"], div[class*="model-response"]',
  loadingIndicator: '.loading-indicator, mat-progress-bar, .thinking-indicator, [class*="loading"], [class*="progress"]',
};

module.exports = {
  name: 'gemini',
  url: 'https://gemini.google.com/app',

  /**
   * Return Google auth cookies to inject before navigating to Gemini.
   *
   * How to get your Gemini session cookies:
   *   1. Open gemini.google.com in your browser and log in with your Google account
   *   2. DevTools (F12) → Application → Cookies → https://gemini.google.com
   *   3. Copy the value of __Secure-1PSID → paste as GEMINI_PSID in .env
   *   4. Copy the value of __Secure-1PSIDTS → paste as GEMINI_PSIDTS in .env
   *   5. Copy the value of __Secure-1PSIDCC → paste as GEMINI_PSIDCC in .env
   */
  getCookies() {
    const { geminiPSID, geminiPSIDTS, geminiPSIDCC } = config;

    if (!geminiPSID || geminiPSID.startsWith('paste_')) {
      throw new Error('GEMINI_PSID not set in .env file. See README for instructions.');
    }

    const cookies = [
      {
        name: '__Secure-1PSID',
        value: geminiPSID,
        domain: '.google.com',
        path: '/',
        httpOnly: true,
        secure: true,
        sameSite: 'None',
      },
    ];

    if (geminiPSIDTS) {
      cookies.push({
        name: '__Secure-1PSIDTS',
        value: geminiPSIDTS,
        domain: '.google.com',
        path: '/',
        httpOnly: true,
        secure: true,
        sameSite: 'None',
      });
    }

    if (geminiPSIDCC) {
      cookies.push({
        name: '__Secure-1PSIDCC',
        value: geminiPSIDCC,
        domain: '.google.com',
        path: '/',
        httpOnly: true,
        secure: true,
        sameSite: 'None',
      });
    }

    return cookies;
  },

  /**
   * Verify that the browser is logged in after navigating to the Gemini page.
   */
  async verifyAuth(page) {
    const url = page.url();
    if (url.includes('accounts.google.com') || url.includes('signin')) {
      throw new Error('Gemini session cookies invalid or expired. Please refresh them from your browser.');
    }

    // Wait for the input box to confirm we're on the chat page
    try {
      await page.waitForSelector(SELECTORS.inputBox, { timeout: 15000 });
    } catch {
      throw new Error('Gemini input box not found. The session may be invalid or the UI changed. Update selectors in providers/gemini.js');
    }
  },

  /**
   * Type a message into Gemini's rich text editor.
   */
  async typeMessage(page, message) {
    const input = await page.waitForSelector(SELECTORS.inputBox, { timeout: 10000 });
    await input.click();

    // Gemini uses a contenteditable div (rich text editor)
    await page.evaluate((sel, text) => {
      const el = document.querySelector(sel);
      if (!el) return;
      el.focus();
      // Clear existing content
      document.execCommand('selectAll');
      document.execCommand('delete');
      // Insert the message
      document.execCommand('insertText', false, text);
    }, SELECTORS.inputBox, message);
  },

  /**
   * Click the send button.
   */
  async clickSend(page) {
    const sendBtn = await page.waitForSelector(SELECTORS.sendButton, { timeout: 5000 });
    await sendBtn.click();
  },

  /**
   * Wait for the response to finish streaming.
   */
  async waitForResponse(page) {
    // Strategy 1: Wait for stop button to appear then disappear
    try {
      await page.waitForSelector(SELECTORS.stopButton, { timeout: 10000 });
      await page.waitForFunction(
        (sel) => !document.querySelector(sel),
        { timeout: 120000, polling: 500 },
        SELECTORS.stopButton
      );
      return;
    } catch {
      // Stop button approach failed
    }

    // Strategy 2: Wait for loading/progress indicator to disappear
    try {
      await page.waitForSelector(SELECTORS.loadingIndicator, { timeout: 5000 });
      await page.waitForFunction(
        (sel) => !document.querySelector(sel),
        { timeout: 120000, polling: 500 },
        SELECTORS.loadingIndicator
      );
      return;
    } catch {
      // No loading indicator
    }

    // Strategy 3: DOM stabilization — wait for content to stop changing
    await page.waitForFunction(
      (responseSel) => {
        const containers = document.querySelectorAll(responseSel);
        if (!containers.length) return false;
        const last = containers[containers.length - 1];
        const currentText = last.textContent;
        if (!window.__geminiLastText) {
          window.__geminiLastText = currentText;
          window.__geminiLastTime = Date.now();
          return false;
        }
        if (currentText !== window.__geminiLastText) {
          window.__geminiLastText = currentText;
          window.__geminiLastTime = Date.now();
          return false;
        }
        return (Date.now() - window.__geminiLastTime) > 3000;
      },
      { timeout: 120000, polling: 500 },
      SELECTORS.responseContainer
    );
  },

  /**
   * Scrape the last response from the DOM.
   */
  async scrapeResponse(page) {
    const response = await page.evaluate((sel) => {
      const containers = document.querySelectorAll(sel);
      if (!containers.length) return null;
      const last = containers[containers.length - 1];

      // Try code blocks first
      const codeBlocks = last.querySelectorAll('pre code');
      if (codeBlocks.length > 0) {
        return Array.from(codeBlocks)
          .map(el => el.textContent?.trim() ?? '')
          .filter(Boolean)
          .join('\n');
      }

      // Walk DOM preserving inline code backticks
      const walk = (node) => {
        if (node.nodeType === 3) return node.textContent ?? '';
        if (node.nodeName === 'CODE' && node.parentElement?.nodeName !== 'PRE') {
          return '`' + (node.textContent ?? '') + '`';
        }
        return Array.from(node.childNodes).map(walk).join('');
      };

      return walk(last).trim();
    }, SELECTORS.responseContainer);

    return response;
  },

  /**
   * Navigate to a fresh chat to avoid context bleed.
   */
  async startNewChat(page) {
    await page.goto(this.url, { waitUntil: 'networkidle2', timeout: 30000 });
    await page.waitForSelector(SELECTORS.inputBox, { timeout: 10000 });
  },
};
