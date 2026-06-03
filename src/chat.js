/**
 * Generic Chat Orchestrator
 *
 * Provider-agnostic message sending logic. Delegates all provider-specific
 * operations (typing, sending, waiting, scraping) to the active provider.
 *
 * Replaces the old chatgpt.js — same mutex, same flow, but works with
 * any provider that implements the standard interface.
 */
const { getPage } = require('./browser');

let provider = null;
let busy = false;

function setProvider(p) {
  provider = p;
}

async function sendMessage(message) {
  if (busy) {
    throw new Error('A request is already in progress. Try again shortly.');
  }

  busy = true;
  try {
    return await _doSendMessage(message);
  } finally {
    busy = false;
  }
}

async function _doSendMessage(message) {
  if (!provider) throw new Error('Provider not initialized. Call setProvider() first.');

  const page = getPage();

  // Start a fresh chat to avoid context bleed between API calls
  await provider.startNewChat(page);

  // Type the message
  await provider.typeMessage(page, message);

  // Click send
  await provider.clickSend(page);

  // Wait for the response to finish streaming
  await provider.waitForResponse(page);

  // Small buffer to let DOM settle after streaming ends
  await delay(500);

  // Scrape the response
  const response = await provider.scrapeResponse(page);

  if (!response) {
    throw new Error(`Could not scrape response from ${provider.name}.`);
  }

  return response;
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isBusy() {
  return busy;
}

function getProviderName() {
  return provider?.name ?? 'unknown';
}

module.exports = { sendMessage, isBusy, setProvider, getProviderName };
