const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
const path = require('path');
const os = require('os');
const fs = require('fs');
const { getProvider } = require('./providers');
const config = require('./config');

puppeteer.use(StealthPlugin());

/**
 * Find the Chrome executable to use.
 * Priority:
 *   1. CHROME_EXECUTABLE_PATH env var (user override)
 *   2. Puppeteer's own bundled Chrome (cross-platform, always present after npm install)
 *   3. System Chrome (common install paths per OS)
 */
function findChrome() {
  // 1. Explicit override via env
  if (config.chromeExecutablePath) {
    console.log(`[browser] Using Chrome from env: ${config.chromeExecutablePath}`);
    return config.chromeExecutablePath;
  }

  // 2. Puppeteer's bundled Chrome
  try {
    const { executablePath } = require('puppeteer');
    const bundled = executablePath();
    if (bundled && fs.existsSync(bundled)) {
      console.log(`[browser] Using Puppeteer bundled Chrome: ${bundled}`);
      return bundled;
    }
  } catch (_) {}

  // 3. Common system Chrome paths
  const platform = os.platform();
  const candidates =
    platform === 'win32'
      ? [
          'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
          'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
          process.env.LOCALAPPDATA + '\\Google\\Chrome\\Application\\chrome.exe',
        ]
      : platform === 'darwin'
      ? [
          '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
          '/Applications/Chromium.app/Contents/MacOS/Chromium',
        ]
      : [
          '/usr/bin/google-chrome',
          '/usr/bin/chromium-browser',
          '/usr/bin/chromium',
        ];

  for (const p of candidates) {
    if (p && fs.existsSync(p)) {
      console.log(`[browser] Using system Chrome: ${p}`);
      return p;
    }
  }

  // Let Puppeteer try with no executablePath (it will error with a clear message)
  console.log('[browser] No Chrome found — letting Puppeteer use its default');
  return undefined;
}

let browser = null;
let page = null;

/**
 * Returns the Chrome user data directory based on the platform.
 * If CHROME_USER_DATA_DIR is set in .env, that is used instead.
 */
function getChromeUserDataDir() {
  if (config.chromeUserDataDir) return config.chromeUserDataDir;

  // Use a local directory for the Puppeteer profile.
  // This avoids locking conflicts with the user's main Chrome browser,
  // and allows the session to be saved persistently after a manual login.
  return path.join(__dirname, '..', 'chrome-data');
}

async function initBrowser() {
  const provider = getProvider();
  const userDataDir = getChromeUserDataDir();

  console.log(`[browser] Launching Puppeteer for provider: ${provider.name}...`);

  const executablePath = findChrome();

  const launchOptions = {
    headless: false,
    ...(executablePath ? { executablePath } : {}),
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-dev-shm-usage',
      '--disable-blink-features=AutomationControlled',
    ],
    ignoreDefaultArgs: ['--enable-automation'],
    defaultViewport: null,
  };

  // Use the real Chrome profile if available
  if (userDataDir) {
    launchOptions.userDataDir = userDataDir;
    console.log(`[browser] Using Chrome profile: ${userDataDir}`);
  } else {
    console.log('[browser] No Chrome profile found, falling back to cookie injection...');
  }

  browser = await puppeteer.launch(launchOptions);
  page = await browser.newPage();

  // Always try to inject cookies if provided in .env
  console.log(`[browser] Navigating to ${provider.url} to establish domain context...`);
  await page.goto(provider.url, { waitUntil: 'domcontentloaded', timeout: 60000 });
  try {
    const cookies = provider.getCookies();
    if (cookies && cookies.length > 0) {
      await page.setCookie(...cookies);
      console.log(`[browser] Injected ${cookies.length} auth cookie(s) for ${provider.name}`);
    }
  } catch (err) {
    console.log(`[browser] Skipping cookie injection: ${err.message}`);
  }

  // Reload to apply cookies
  console.log(`[browser] Loading ${provider.url} with cookies...`);
  await page.goto(provider.url, { waitUntil: 'networkidle2', timeout: 60000 });

  console.log(`[browser] ${provider.name} loaded. Checking auth...`);
  try {
    await provider.verifyAuth(page);
    console.log('[browser] Auth verified. Ready.');
  } catch (err) {
    console.log(`\n======================================================`);
    console.log(`⚠️  AUTH FAILED: Automatically launching secure login window...`);
    console.log(`======================================================`);
    console.log(`Please log in using the newly opened window.`);
    
    const { execSync } = require('child_process');
    try {
      execSync(`python src/login_helper.py ${provider.name} "${provider.url}"`, { stdio: 'inherit' });
    } catch (e) {
      console.error("[browser] Login window closed or failed.");
      throw new Error("Login failed or was cancelled.");
    }
    
    console.log(`\n======================================================`);
    console.log(`✅  Login complete! Restarting browser with new cookies...`);
    console.log(`======================================================\n`);
    
    // Reload env and config
    config.reload();
    
    // Close current page and retry with new cookies
    await page.close();
    page = await browser.newPage();
    
    await page.goto(provider.url, { waitUntil: 'domcontentloaded', timeout: 60000 });
    try {
      const newCookies = provider.getCookies();
      if (newCookies && newCookies.length > 0) {
        await page.setCookie(...newCookies);
        console.log(`[browser] Injected ${newCookies.length} newly saved cookie(s)`);
      }
    } catch (cookieErr) {
      console.log(`[browser] Still failed to get cookies: ${cookieErr.message}`);
    }
    
    await page.goto(provider.url, { waitUntil: 'networkidle2', timeout: 60000 });
    await provider.verifyAuth(page);
    console.log('[browser] Auth verified after manual login. Ready.');
  }

  return provider;
}

function getPage() {
  if (!page) throw new Error('Browser not initialized. Call initBrowser() first.');
  return page;
}

async function closeBrowser() {
  if (browser) await browser.close();
}

module.exports = { initBrowser, getPage, closeBrowser };
