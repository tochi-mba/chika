/**
 * security.js — client-side security checks (defense-in-depth)
 *
 * The server also validates these, but the extension is the last line.
 * Never trust the network alone.
 */

// Domains where write actions are always blocked
const WRITE_BLOCKED_DOMAINS = new Set([
  'bankofamerica.com',
  'chase.com',
  'wellsfargo.com',
  'citibank.com',
  'hsbc.com',
  'paypal.com',
  'stripe.com',
  'braintreegateway.com',
  'coinbase.com',
  'binance.com',
  'kraken.com',
  'accounts.google.com',
  'login.microsoftonline.com',
  'login.live.com',
  'appleid.apple.com',
  'auth.apple.com',
  'login.yahoo.com',
  'lastpass.com',
  '1password.com',
  'bitwarden.com',
  'dashlane.com',
])

// Chrome internal / extension pages that scripts can't access
const RESTRICTED_URL_PREFIXES = [
  'chrome://',
  'chrome-extension://',
  'chrome-devtools://',
  'edge://',
  'about:',
  'data:',
  'javascript:',
]

/**
 * Returns true if write actions (navigate, click, fill) are blocked on this URL.
 */
export function isWriteBlocked(url) {
  if (!url) return true
  try {
    const hostname = new URL(url).hostname.toLowerCase()
    for (const blocked of WRITE_BLOCKED_DOMAINS) {
      if (hostname === blocked || hostname.endsWith('.' + blocked)) {
        return true
      }
    }
    return false
  } catch {
    return true // malformed URL → block
  }
}

/**
 * Returns true if executeScript cannot be used on this URL.
 */
export function isRestrictedUrl(url) {
  if (!url) return true
  for (const prefix of RESTRICTED_URL_PREFIXES) {
    if (url.startsWith(prefix)) return true
  }
  return false
}

/**
 * Write actions that require the "action" allowlist.
 * ANY action not in this list is rejected immediately.
 */
const ALLOWED_ACTIONS = new Set([
  'get_tab_list',
  'get_active_tab',
  'get_tab_text',
  'get_page_var',
  'get_tab_dom',
  'get_element',
  'screenshot',
  'navigate',
  'open_tab',
  'close_tab',
  'switch_tab',
  'click',
  'fill_input',
  'scroll',
  'watch_element',
  'unwatch',
  'list_watches',
])

export function isAllowedAction(action) {
  return ALLOWED_ACTIONS.has(action)
}

// Max sizes
export const MAX_TEXT_BYTES  = 500_000   // 500KB per page text
export const MAX_DOM_BYTES   = 2_000_000  // 2MB for DOM
export const MAX_VALUE_LEN   = 10_000    // form input
export const MAX_SELECTOR_LEN = 500
