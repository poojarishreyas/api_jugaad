const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
const path = require('path');
const os = require('os');
const { getProvider } = require('./providers');
const config = require('./config');

puppeteer.use(StealthPlugin());

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

  const launchOptions = {
    headless: false,
    executablePath: '/usr/bin/google-chrome',
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-dev-shm-usage',
      '--disable-blink-features=AutomationControlled',
    ],
    defaultViewport: null, // Use window size instead of fixed viewport
  };

  // Use the real Chrome profile if available — this gives us all cookies,
  // local storage, and session data without needing to copy anything.
  if (userDataDir) {
    launchOptions.userDataDir = userDataDir;
    console.log(`[browser] Using Chrome profile: ${userDataDir}`);
  } else {
    // Fallback: inject cookies manually
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
    console.log(`⚠️  ACTION REQUIRED: PLEASE LOG IN MANUALLY`);
    console.log(`======================================================`);
    console.log(`Puppeteer is running in headless: false mode.`);
    console.log(`Please use the opened Chrome window to log into ${provider.name}.`);
    console.log(`Waiting for you to log in...`);
    console.log(`======================================================\n`);

    // Loop until verifyAuth succeeds
    let loggedIn = false;
    while (!loggedIn) {
      try {
        await new Promise(resolve => setTimeout(resolve, 5000));
        await provider.verifyAuth(page);
        loggedIn = true;
        console.log('[browser] Login detected! Auth verified. Ready.');
      } catch (e) {
        // Still not logged in, keep waiting
      }
    }
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
