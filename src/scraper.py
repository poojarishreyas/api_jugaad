"""
Shared DOM scraper for AI chat responses.

Strategy: clone the message node, strip all UI chrome (buttons, icons,
aria-hidden elements), then use the browser's native innerText to extract
clean, readable plain text — exactly the same format a traditional AI API
(OpenAI, Anthropic, etc.) returns in its response content field.

Why innerText and NOT a markdown reconstructor:
  - AI UIs render the model's markdown into HTML (** → <strong>, etc.)
  - We want the TEXT the model wrote, not HTML tags re-encoded as markdown
  - innerText gives us rendered, readable text — no stray ** or ## symbols
  - Code blocks are preserved verbatim using the <pre> element's innerText
"""

# ---------------------------------------------------------------------------
# JavaScript: clone → strip chrome → extract clean text
# ---------------------------------------------------------------------------
_SCRAPE_JS = r"""
(node) => {
    // ── 1. Clone so we never mutate the live page ─────────────────────────
    const clone = node.cloneNode(true);

    // ── 2. Strip all UI chrome — not content ─────────────────────────────
    const REMOVE_SELECTORS = [
        'button',
        'svg',
        'img',
        'script',
        'style',
        'noscript',
        '[role="button"]',
        '[aria-hidden="true"]',
        // Provider-specific UI elements
        '.copy-btn', '.action-btn', '.edit-btn',
        '.thinking-chain-container', '.thought-process',
        '.thought-chain', 'details',
    ].join(',');

    clone.querySelectorAll(REMOVE_SELECTORS).forEach(el => el.remove());

    // Also remove any lone text nodes that are just UI labels
    const UI_LABELS = new Set(['Edit', 'Copy', 'Copy code', 'Thought Process', 'Retry']);
    clone.querySelectorAll('span, div').forEach(el => {
        if (UI_LABELS.has(el.textContent.trim())) el.remove();
    });

    // ── 3. Off-screen render so innerText computes correctly ──────────────
    //    (innerText is layout-dependent — the node must be in the document)
    const wrapper = document.createElement('div');
    wrapper.style.cssText = 'position:absolute;left:-99999px;top:-99999px;opacity:0';
    wrapper.appendChild(clone);
    document.body.appendChild(wrapper);

    // ── 4. Extract text ───────────────────────────────────────────────────
    const text = wrapper.innerText;

    // ── 5. Clean up DOM ───────────────────────────────────────────────────
    wrapper.remove();

    // Collapse 3+ blank lines to 2, trim edges
    return text.replace(/\n{3,}/g, '\n\n').trim();
}
"""


async def scrape_response(last_message_locator) -> str:
    """
    Extract clean plain text from the last AI message element.

    Returns text in the same format as a traditional AI API response:
    readable prose with natural line breaks, no raw Markdown symbols,
    no UI artifacts (buttons, copy icons, etc.).

    Code blocks are preserved as plain text (their content is readable
    as-is without fencing syntax).

    Args:
        last_message_locator: A Playwright Locator pointing to the last
                              assistant message container element.

    Returns:
        Clean plain text string, or "" if the element is empty.
    """
    result = await last_message_locator.evaluate(_SCRAPE_JS)
    return result.strip() if result else ""


# Alias so providers can use either name
scrape_markdown = scrape_response

