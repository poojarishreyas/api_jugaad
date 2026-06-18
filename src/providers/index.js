/**
 * Provider Factory
 *
 * Loads the correct AI provider module based on the PROVIDER env var.
 * Supported: chatgpt, zai, gemini
 */
const config = require('../config');

const PROVIDERS = {
  chatgpt: () => require('./chatgpt'),
  zai:     () => require('./zai'),
  gemini:  () => require('./gemini'),
};

function getProvider() {
  const name = config.provider;
  const loader = PROVIDERS[name];

  if (!loader) {
    const supported = Object.keys(PROVIDERS).join(', ');
    throw new Error(`Unknown provider "${name}". Supported providers: ${supported}`);
  }

  const provider = loader();
  console.log(`[provider] Using provider: ${provider.name}`);
  return provider;
}

module.exports = { getProvider };
