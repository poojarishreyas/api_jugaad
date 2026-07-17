/**
 * Z.ai (Zhipu GLM) Provider
 *
 * Drives the z.ai web UI via Puppeteer.
 * Auth: session cookie from browser DevTools.
 *
 * Selectors verified from the live z.ai DOM (July 2026).
 * If Z.ai redesigns their UI, update the SELECTORS object below.
 */
const config = require('../config');

// ── Z.ai DOM selectors (verified from live site) ──────────────
const SELECTORS = {
  // <textarea id="chat-input" placeholder="How can I help you today?">
  inputBox: '#chat-input',
  // <button id="send-message-button" type="submit" aria-label="Send Message">
  sendButton: '#send-message-button',
  // Stop button — appears during streaming (inspect live to confirm exact selector)
  stopButton: 'button[aria-label="Stop"], button.stop-btn',
  // <div class="markdown-prose"> wraps each assistant response
  assistantMessage: '.markdown-prose',
  // <div class="thinking-chain-container"> appears while "Deep Think" is active
  thinkingChain: '.thinking-chain-container',
  loadingIndicator: '.thinking-chain-container[data-direct="false"], [class*="loading"], [class*="typing"]',
};

module.exports = {
  name: 'zai',
  url: 'https://chat.z.ai/',

  /**
   * Return cookies to inject before navigating to the chat page.
   *
   * OPTION A (Recommended) — ZAI_COOKIES in .env:
   *   Paste ALL cookies from DevTools as a JSON array.
   *   In DevTools → Application → Cookies → chat.z.ai, right-click any cookie
   *   and use "Copy all cookies as JSON" or manually build the array:
   *   ZAI_COOKIES=[{"name":"oauth_id_token","value":"eyJ..."},{"name":"acw_tc","value":"..."}]
   *
   * OPTION B — ZAI_SESSION_COOKIE in .env:
   *   Only the oauth_id_token value (may not be enough to authenticate).
   */
  getCookies() {
    const { zaiCookies, zaiSessionCookie } = config;

    // Option A: full cookie JSON array
    if (zaiCookies) {
      try {
        const parsed = JSON.parse(zaiCookies);
        return parsed.map(c => ({
          ...c,
          domain: c.domain || 'chat.z.ai',
          path: c.path || '/',
          secure: c.secure ?? false,
          sameSite: c.sameSite || 'Lax',
        }));
      } catch (e) {
        throw new Error(`ZAI_COOKIES is not valid JSON: ${e.message}`);
      }
    }

    // Option B: single oauth_id_token fallback
    if (zaiSessionCookie && !zaiSessionCookie.startsWith('paste_')) {
      return [
        {
          name: 'oauth_id_token',
          value: zaiSessionCookie,
          domain: 'chat.z.ai',
          path: '/',
          httpOnly: false,
          secure: false,
          sameSite: 'Lax',
        },
      ];
    }

    // Option C: Manual login via Puppeteer (no cookies configured)
    return [];
  },

  /**
   * Verify that the browser is logged in after navigating to the chat page.
   */
  async verifyAuth(page) {
    const url = page.url();
    if (url.includes('login') || url.includes('sign-in') || url.includes('auth')) {
      throw new Error('Z.ai session cookie invalid or expired. Please refresh it from your browser.');
    }
    
    // Explicitly check for auth cookies because Z.ai has a chat box even when logged out
    const cookies = await page.cookies();
    const hasAuthCookie = cookies.some(c => c.name === 'acw_tc' || c.name === 'oauth_id_token' || c.name.includes('token') || c.name.includes('session'));
    
    if (!hasAuthCookie) {
      // Check if there is a visible login button on the page as a fallback check
      const hasLoginBtn = await page.evaluate(() => {
        return Array.from(document.querySelectorAll('button, a')).some(el => 
          el.textContent.toLowerCase().includes('log in') || 
          el.textContent.toLowerCase().includes('sign in')
        );
      });
      if (hasLoginBtn || cookies.length < 3) {
        throw new Error('Not logged in. Missing Z.ai auth cookies.');
      }
    }

    // Wait for the input box to confirm we're on the chat page
    try {
      await page.waitForSelector(SELECTORS.inputBox, { timeout: 15000 });
    } catch {
      throw new Error('Z.ai input box not found. The session may be invalid or the UI changed. Update selectors in providers/zai.js');
    }
  },

  /**
   * Type a message into Z.ai's textarea input.
   * Z.ai uses a standard <textarea id="chat-input">, not contenteditable.
   */
  async typeMessage(page, message) {
    const input = await page.waitForSelector(SELECTORS.inputBox, { timeout: 10000 });
    await input.click();

    // Set value directly and dispatch input event to trigger any framework reactivity
    await page.evaluate((sel, text) => {
      const el = document.querySelector(sel);
      // Use native setter to bypass framework getter/setter overrides
      const nativeSetter = Object.getOwnPropertyDescriptor(
        window.HTMLTextAreaElement.prototype, 'value'
      ).set;
      nativeSetter.call(el, text);
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
    }, SELECTORS.inputBox, message);
  },

  /**
   * Click send and wait for Z.ai to navigate to the new chat URL (chat.z.ai/c/...).
   * Z.ai creates a new chat page after submitting, which detaches the old frame.
   * We use Promise.all to click and watch for navigation simultaneously.
   */
  async clickSend(page) {
    const sendBtn = await page.waitForSelector(SELECTORS.sendButton, { timeout: 5000 });

    // Click and wait for navigation together — Z.ai redirects to /c/<id> after sending
    await Promise.all([
      page.waitForNavigation({ waitUntil: 'domcontentloaded', timeout: 15000 }).catch(() => {
        // No navigation happened (e.g. follow-up in existing chat) — that's fine
      }),
      sendBtn.click(),
    ]);
  },

  /**
   * Wait for the response to finish streaming/loading.
   */
  async waitForResponse(page) {
    console.log('[zai] Waiting for assistant message to appear...');
    await page.waitForSelector(SELECTORS.assistantMessage, { timeout: 30000 });
    console.log('[zai] Assistant message found. Waiting for streaming to finish...');

    // Strategy 1: Stop button appears then disappears
    try {
      await page.waitForSelector(SELECTORS.stopButton, { timeout: 5000 });
      console.log('[zai] Stop button detected. Waiting for it to disappear...');
      await page.waitForFunction(
        (sel) => !document.querySelector(sel),
        { timeout: 120000, polling: 500 },
        SELECTORS.stopButton
      );
      console.log('[zai] Stop button disappeared. Response complete.');
      return;
    } catch {
      console.log('[zai] No stop button detected. Falling back to DOM stabilization...');
    }

    // Strategy 2: DOM stabilization — content stops changing for 2.5 seconds
    console.log('[zai] Watching DOM for stabilization...');
    await page.waitForFunction(
      () => {
        const msgs = document.querySelectorAll('.markdown-prose');
        if (!msgs.length) return false;
        const last = msgs[msgs.length - 1];
        const currentText = last.textContent;
        
        if (!window.__zaiLastText) {
          window.__zaiLastText = currentText;
          window.__zaiLastTime = Date.now();
          return false;
        }
        
        if (currentText !== window.__zaiLastText) {
          window.__zaiLastText = currentText;
          window.__zaiLastTime = Date.now();
          return false;
        }
        
        return (Date.now() - window.__zaiLastTime) > 2500;
      },
      { timeout: 120000, polling: 500 }
    );
    console.log('[zai] DOM stabilized. Response complete.');
  },

  /**
   * Scrape the last assistant message from the DOM.
   * Skips the .thinking-chain-container (Deep Think's "Thought Process")
   * and extracts only the actual response text from .markdown-prose.
   */
  async scrapeResponse(page) {
    const response = await page.evaluate((sel) => {
      const messages = document.querySelectorAll(sel);
      if (!messages.length) return null;
      const last = messages[messages.length - 1];

      // Try code blocks first
      const codeBlocks = last.querySelectorAll('pre code');
      if (codeBlocks.length > 0) {
        return Array.from(codeBlocks)
          .map(el => el.textContent?.trim() ?? '')
          .filter(Boolean)
          .join('\n');
      }

      // Walk DOM, skip the thinking chain, restore inline code backticks
      const walk = (node) => {
        if (node.nodeType === 3) return node.textContent ?? '';
        // Skip the "Thought Process" thinking chain
        if (node.classList?.contains('thinking-chain-container')) return '';
        if (node.nodeName === 'CODE' && node.parentElement?.nodeName !== 'PRE') {
          return '`' + (node.textContent ?? '') + '`';
        }
        return Array.from(node.childNodes).map(walk).join('');
      };

      return walk(last).trim();
    }, SELECTORS.assistantMessage);

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
