/**
 * Deployment setting: where the Anviq API answers the web room.
 * Empty means "same place this page is served from" (useful when the API proxies the page).
 * For the demo stack put the public API URL here, e.g.:
 *   window.ANVIQ_API_BASE = "https://anviq-demo.duckdns.org";
 * A per-visit ?api= query parameter overrides this, which lets the page be tested
 * against a local API without editing deployed files.
 */
window.ANVIQ_API_BASE = "";
