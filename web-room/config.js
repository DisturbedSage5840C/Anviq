/**
 * Deployment setting: where the Anviq API answers the web room.
 * Empty means "same place this page is served from" (useful when the API proxies the page).
 * For the demo stack put the public API URL here, e.g.:
 *   window.ANVIQ_API_BASE = "https://35-200-176-62.sslip.io";
 * A per-visit ?api= query parameter overrides this only when the page is opened from
 * localhost, which lets the page be tested against a local API without editing files.
 * On any other host it is ignored, so a crafted link cannot redirect the demo code.
 */
window.ANVIQ_API_BASE = "";
