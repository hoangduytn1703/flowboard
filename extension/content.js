/**
 * Content script — bridge between background.js (ISOLATED world) and
 * injected.js (MAIN world); forwards GET_CAPTCHA messages.
 *
 * injected.js is loaded by manifest.json as a "world": "MAIN" content script.
 * It used to be injected a second time from here with a <script> tag, and that
 * copy died on "Identifier 'SITE_KEY' has already been declared".
 */

chrome.runtime.onMessage.addListener((msg, _, reply) => {
  if (msg.type !== 'GET_CAPTCHA') return;

  const { requestId, pageAction } = msg;

  const handler = (e) => {
    if (e.detail?.requestId === requestId) {
      window.removeEventListener('CAPTCHA_RESULT', handler);
      clearTimeout(timer);
      reply({ token: e.detail.token, error: e.detail.error });
    }
  };

  const timer = setTimeout(() => {
    window.removeEventListener('CAPTCHA_RESULT', handler);
    reply({ error: 'CONTENT_TIMEOUT' });
  }, 25000);

  window.addEventListener('CAPTCHA_RESULT', handler);

  window.dispatchEvent(new CustomEvent('GET_CAPTCHA', {
    detail: { requestId, pageAction },
  }));

  return true; // keep channel open for async reply
});
