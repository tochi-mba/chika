// ─────────────────────────────────────────────────────────────────────
//  Chika landing — interactivity (vanilla JS, no build).
//
//  Responsibilities:
//    1. Detect the visitor's OS, label the primary CTA accordingly.
//    2. Hit GitHub Releases (latest), retarget per-OS install cards
//       at the right asset URLs, populate asset filenames.
//    3. Animate the terminal mock: triangle rotation, verb cycle,
//       elapsed-time counter — same vocabulary the CLI uses.
//    4. Mobile nav toggle (hamburger).
//    5. Copy-to-clipboard for shell snippets.
//
//  Edge cases:
//    - GitHub API rate-limited / 404 → graceful fallback to releases
//      page, asset-name fields show a static placeholder.
//    - Reduced-motion users → all setIntervals respect
//      prefers-reduced-motion (set once at boot).
//    - No clipboard API (older browsers) → fall back to
//      document.execCommand('copy') on a hidden textarea.
// ─────────────────────────────────────────────────────────────────────

const REPO = 'tochi-mba/chika';
const RELEASES_URL = `https://github.com/${REPO}/releases/latest`;

const VERBS = [
  'investigating', 'tracing', 'piecing together',
  'reading', 'cross-referencing', 'thinking',
];

const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

// ── Terminal mock animations ────────────────────────────────────────

function startTerminalMock() {
  if (reduce) return;

  const triangles = [
    document.querySelector('.tri-left'),
    document.querySelector('.tri-mid'),
    document.querySelector('.tri-right'),
  ].filter(Boolean);

  let triIdx = 0;
  setInterval(() => {
    triIdx = (triIdx + 1) % 3;
    triangles.forEach((t, i) => t.classList.toggle('active', i === triIdx));
  }, 700);

  const verbEl = document.getElementById('state-verb');
  let verbIdx = 0;
  setInterval(() => {
    verbIdx = (verbIdx + 1) % VERBS.length;
    if (verbEl) verbEl.textContent = VERBS[verbIdx];
  }, 2200);

  const timerEl = document.getElementById('state-elapsed');
  let elapsed = 2.3;
  setInterval(() => {
    elapsed = +(elapsed + 0.1).toFixed(1);
    if (elapsed > 4.7) elapsed = 0.3;
    if (timerEl) timerEl.textContent = `${elapsed}s`;
  }, 100);
}

// ── OS detection ────────────────────────────────────────────────────

function detectOS() {
  const ua = (navigator.userAgent || '').toLowerCase();
  const platform = (navigator.platform || '').toLowerCase();
  if (ua.includes('windows') || platform.includes('win')) return 'windows';
  if (ua.includes('mac') || platform.includes('mac')) return 'macos';
  if (ua.includes('linux') || platform.includes('linux')) return 'linux';
  if (/android|iphone|ipad/.test(ua)) return 'mobile';
  return 'unknown';
}

const OS_LABEL = {
  windows: 'for Windows',
  macos:   'for macOS',
  linux:   'for Linux',
  mobile:  '— mobile not supported',
  unknown: 'view all platforms',
};

// ── GitHub Releases ─────────────────────────────────────────────────

async function fetchLatestRelease() {
  try {
    const r = await fetch(`https://api.github.com/repos/${REPO}/releases/latest`, {
      headers: { Accept: 'application/vnd.github+json' },
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.json();
  } catch {
    return null;
  }
}

function findAsset(release, suffix) {
  if (!release || !Array.isArray(release.assets)) return null;
  const lower = suffix.toLowerCase();
  return release.assets.find(a =>
    typeof a.name === 'string' && a.name.toLowerCase().endsWith(lower)
  ) || null;
}

function setAsset(id, asset) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = asset.name;
}

function setAssetText(id, text) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = text;
}

function retargetCard(os, asset) {
  const card = document.querySelector(`.install-card[data-os="${os}"]`);
  if (!card || !asset) return;
  card.setAttribute('href', asset.browser_download_url);
}

// ── Mobile nav toggle ───────────────────────────────────────────────

function wireNavToggle() {
  const toggle = document.getElementById('nav-toggle');
  const links = document.getElementById('nav-links');
  if (!toggle || !links) return;
  toggle.addEventListener('click', () => {
    const expanded = toggle.getAttribute('aria-expanded') === 'true';
    toggle.setAttribute('aria-expanded', String(!expanded));
    links.classList.toggle('active', !expanded);
  });
  // Close menu when a link is tapped (mobile navigation feels broken
  // otherwise — clicking a hash link doesn't visibly do anything if
  // the menu stays open above the section).
  links.querySelectorAll('a').forEach((a) => {
    a.addEventListener('click', () => {
      toggle.setAttribute('aria-expanded', 'false');
      links.classList.remove('active');
    });
  });
}

// ── Copy buttons ────────────────────────────────────────────────────

async function writeToClipboard(text) {
  if (navigator.clipboard?.writeText) {
    try { await navigator.clipboard.writeText(text); return true; } catch { /* fall through */ }
  }
  // Legacy fallback for browsers without async clipboard.
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}

function wireCopyButtons() {
  document.querySelectorAll('.copy-btn').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const targetId = btn.getAttribute('data-copy-target');
      const target = targetId && document.getElementById(targetId);
      const text = target ? target.textContent.trim() : '';
      if (!text) return;
      const ok = await writeToClipboard(text);
      if (ok) {
        btn.classList.add('copied');
        setTimeout(() => btn.classList.remove('copied'), 1800);
      }
    });
  });
}

// ── Init ────────────────────────────────────────────────────────────

async function init() {
  startTerminalMock();
  wireNavToggle();
  wireCopyButtons();

  const os = detectOS();
  const primary = document.getElementById('primary-download');
  const primarySub = document.getElementById('primary-download-os');
  if (primarySub) primarySub.textContent = OS_LABEL[os] || OS_LABEL.unknown;

  const release = await fetchLatestRelease();
  if (!release) {
    setAssetText('windows-asset', 'see github releases');
    setAssetText('macos-asset', 'see github releases');
    setAssetText('linux-deb-asset', 'see github releases');
    return;
  }

  const winAsset = findAsset(release, '.exe');
  const macAsset = findAsset(release, '.pkg');
  const debAsset = findAsset(release, '.deb');

  if (winAsset) setAsset('windows-asset', winAsset);
  else          setAssetText('windows-asset', '(no .exe in latest release)');

  if (macAsset) setAsset('macos-asset', macAsset);
  else          setAssetText('macos-asset', '(no .pkg in latest release)');

  if (debAsset) setAsset('linux-deb-asset', debAsset);
  else          setAssetText('linux-deb-asset', '(no .deb in latest release)');

  retargetCard('windows', winAsset);
  retargetCard('macos', macAsset);
  retargetCard('linux', debAsset);

  const target = (
    os === 'windows' ? winAsset :
    os === 'macos'   ? macAsset :
    os === 'linux'   ? debAsset :
    null
  );
  if (target && primary) primary.setAttribute('href', target.browser_download_url);
}

if (document.readyState !== 'loading') init();
else document.addEventListener('DOMContentLoaded', init);
