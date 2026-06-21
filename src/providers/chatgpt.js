/**
 * ChatGPT Provider
 *
 * Drives the chatgpt.com web UI via Puppeteer.
 * Auth: split session cookies (__Secure-next-auth.session-token.0 and .1)
 */
const config = require('../config');

const SELECTORS = {
  inputBox: '#prompt-textarea',
  sendButton: 'button[data-testid="send-button"]',
  stopButton: 'button[data-testid="stop-button"]',
  assistantMessage: '[data-message-author-role="assistant"]',
};

module.exports = {
  name: 'chatgpt',
  url: 'https://chatgpt.com/',

  /**
   * Return cookies to inject before navigating to the chat page.
   */
  getCookies() {
    const { sessionToken0, sessionToken1 } = config;

    if (!sessionToken0 || sessionToken0.startsWith('paste_')) {
      throw new Error('SESSION_TOKEN_0 not set in .env file');
    }
    if (!sessionToken1 || sessionToken1.startsWith('paste_')) {
      throw new Error('SESSION_TOKEN_1 not set in .env file');
    }

    return [
      {
        name: '__Secure-next-auth.session-token.0',
        value: sessionToken0,
        domain: 'chatgpt.com',
        path: '/',
        httpOnly: true,
        secure: true,
        sameSite: 'Lax',
      },
      {
        name: '__Secure-next-auth.session-token.1',
        value: sessionToken1,
        domain: 'chatgpt.com',
        path: '/',
        httpOnly: true,
        secure: true,
        sameSite: 'Lax',
      },
    ];
  },

  /**
   * Verify that the browser is logged in after navigating to the chat page.
   */
  async verifyAuth(page) {
    const url = page.url();
    if (url.includes('auth') || url.includes('login')) {
      throw new Error('Session token invalid or expired. Please refresh it from your browser.');
    }

    try {
      await page.waitForSelector(SELECTORS.inputBox, { timeout: 15000 });
    } catch {
      throw new Error('ChatGPT input box not found. The session may be invalid or the UI changed.');
    }
  },

  /**
   * Type a message into ChatGPT's contenteditable prompt div.
   */
  async typeMessage(page, message) {
    const input = await page.waitForSelector(SELECTORS.inputBox, { timeout: 10000 });
    await input.click();
    await page.evaluate((sel, text) => {
      const el = document.querySelector(sel);
      el.focus();
      document.execCommand('selectAll');
      document.execCommand('delete');
      document.execCommand('insertText', false, text);
    }, SELECTORS.inputBox, message);
  },

  /**
   * Click the send button.
   */
  async clickSend(page) {
    try {
      const sendBtn = await page.waitForSelector(SELECTORS.sendButton, { timeout: 3000 });
      await sendBtn.click();
    } catch (e) {
      console.log('[chatgpt] Could not find send button by selector, falling back to Enter key...');
      await page.keyboard.press('Enter');
    }
  },

  /**
   * Wait for streaming to finish (stop button appears, then disappears).
   */
  async waitForResponse(page) {
    // Wait for streaming to start (stop button appears)
    await page.waitForSelector(SELECTORS.stopButton, { timeout: 15000 }).catch(() => {
      // If stop button never appears, ChatGPT may have responded instantly
    });

    // Wait for streaming to finish (stop button disappears)
    await page.waitForFunction(
      (stopSel) => !document.querySelector(stopSel),
      { timeout: 120000, polling: 500 },
      SELECTORS.stopButton
    );
  },

  /**
   * Scrape the last assistant message from the DOM.
   */
  async scrapeResponse(page) {
    const response = await page.evaluate((msgSel) => {
      const messages = document.querySelectorAll(msgSel);
      if (!messages.length) return null;
      const last = messages[messages.length - 1];

      // Path 1: code block — textContent preserves ALL characters including backticks
      const codeBlocks = last.querySelectorAll('pre code');
      if (codeBlocks.length > 0) {
        return Array.from(codeBlocks)
          .map(el => el.textContent?.trim() ?? '')
          .filter(Boolean)
          .join('\n');
      }

      // Path 2: no code block — markdown renderer strips backtick delimiters from
      // inline <code> elements (e.g. template literals become <code>...</code>).
      // Walk the DOM and restore them so the JSON string content stays valid.
      const walk = (node) => {
        if (node.nodeType === 3) return node.textContent ?? '';
        // inline <code> (not inside <pre>) had its backtick delimiters stripped
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
