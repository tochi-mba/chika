// ============================================================
// DRONE STRIKE 3D  —  Three.js r128
// Generative city, first-person drone, enemy drones, waves
// ============================================================
'use strict';

// ── DOM refs ──────────────────────────────────────────────────
const overlay     = document.getElementById('overlay');
const gameoverEl  = document.getElementById('gameover');
const pausedEl    = document.getElementById('paused');
const waveBanner  = document.getElementById('wave-banner');
const reloadWrap  = document.getElementById('reload-wrap');
const reloadFill  = document.getElementById('reload-fill');
const vignette    = document.getElementById('vignette');
const speedlines  = document.getElementById('speedlines');
const hitMarker   = document.getElementById('hit-marker');

const elScore    = document.getElementById('score');
const elWave     = document.getElementById('wave');
const elKills    = document.getElementById('kills');
const elAmmo     = document.getElementById('ammo');
const elAlt      = document.getElementById('altitude');
const elHealthB  = document.getElementById('health-bar');
const goScore    = document.getElementById('go-score');
const goWave     = document.getElementById('go-wave');
const goKills    = document.getElementById('go-kills');

// ── Three.js scene ────────────────────────────────────────────
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 0.85;
renderer.outputEncoding = THREE.sRGBEncoding;
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.domElement.style.position = 'fixed';
renderer.domElement.style.inset = '0';
renderer.domElement.style.zIndex = '1';
document.body.insertBefore(renderer.domElement, document.body.firstChild);

const scene  = new THREE.Scene();
scene.background = new THREE.Color(0x0a0e18);
scene.fog = new THREE.FogExp2(0x0a0e18, 0.0045);

const camera = new THREE.PerspectiveCamera(80, window.innerWidth / window.innerHeight, 0.1, 2000);
camera.position.set(0, 50, 0);

window.addEventListener('resize', () => {
  renderer.setSize(window.innerWidth, window.innerHeight);
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
});

// ── Lighting ─────────────────────────────────────────────────
const ambientLight = new THREE.AmbientLight(0x101828, 1.2);
scene.add(ambientLight);

const sunLight = new THREE.DirectionalLight(0x8899cc, 0.6);
sunLight.position.set(200, 400, 100);
sunLight.castShadow = true;
sunLight.shadow.mapSize.set(2048, 2048);
sunLight.shadow.camera.near = 1;
sunLight.shadow.camera.far  = 1500;
sunLight.shadow.camera.left = sunLight.shadow.camera.bottom = -600;
sunLight.shadow.camera.right = sunLight.shadow.camera.top  = 600;
scene.add(sunLight);

// Moon / haze
const moonLight = new THREE.DirectionalLight(0x2233aa, 0.3);
moonLight.position.set(-300, 200, -200);
scene.add(moonLight);

// Hemisphere
scene.add(new THREE.HemisphereLight(0x0a0e22, 0x111111, 0.5));

// ── Sky / Stars ───────────────────────────────────────────────
(function buildStars() {
  const geo = new THREE.BufferGeometry();
  const pos = [];
  for (let i = 0; i < 3000; i++) {
    const theta = Math.random() * Math.PI * 2;
    const phi   = Math.acos(2 * Math.random() - 1);
    const r     = 900 + Math.random() * 100;
    pos.push(
      r * Math.sin(phi) * Math.cos(theta),
      r * Math.sin(phi) * Math.sin(theta),
      r * Math.cos(phi)
    );
  }
  geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  const mat = new THREE.PointsMaterial({ color: 0xffffff, size: 1.2, sizeAttenuation: true });
  scene.add(new THREE.Points(geo, mat));
})();

// ── Terrain ───────────────────────────────────────────────────
const WORLD = 600;
const groundGeo  = new THREE.PlaneGeometry(WORLD * 3, WORLD * 3, 80, 80);
// Slight vertex displacement for uneven ground
(function bumpGround() {
  const pos = groundGeo.attributes.position;
  for (let i = 0; i < pos.count; i++) {
    pos.setZ(i, (Math.random() - 0.5) * 1.4);
  }
  groundGeo.computeVertexNormals();
})();

const groundMat = new THREE.MeshLambertMaterial({
  color: 0x0d1117,
});
const ground = new THREE.Mesh(groundGeo, groundMat);
ground.rotation.x = -Math.PI / 2;
ground.receiveShadow = true;
scene.add(ground);

// Road grid lines
(function buildRoads() {
  const mat = new THREE.MeshBasicMaterial({ color: 0x1a1f2e });
  const ROAD_W = 8;
  const spacing = 80;
  for (let x = -WORLD; x <= WORLD; x += spacing) {
    const g = new THREE.PlaneGeometry(ROAD_W, WORLD * 2);
    const m = new THREE.Mesh(g, mat);
    m.rotation.x = -Math.PI / 2;
    m.position.set(x, 0.05, 0);
    scene.add(m);
  }
  for (let z = -WORLD; z <= WORLD; z += spacing) {
    const g = new THREE.PlaneGeometry(WORLD * 2, ROAD_W);
    const m = new THREE.Mesh(g, mat);
    m.rotation.x = -Math.PI / 2;
    m.position.set(0, 0.05, z);
    scene.add(m);
  }
})();

// ── Procedural City ───────────────────────────────────────────
const BUILDING_COLORS = [
  0x1a2030, 0x151c28, 0x0f1520, 0x1c2235,
  0x202838, 0x111926, 0x1a2440,
];
const WINDOW_COLORS   = [0xfff8d0, 0xffd080, 0x80d0ff, 0xff8040];

const buildingMeshes = [];

function rng(seed) {
  let s = seed;
  return () => { s = (s * 1664525 + 1013904223) & 0xffffffff; return (s >>> 0) / 0xffffffff; };
}

function buildCity() {
  const BLOCK = 80;
  const GAP   = 8;
  let seed = 42;
  let srand = rng(seed);

  for (let bx = -WORLD + BLOCK / 2; bx < WORLD; bx += BLOCK) {
    for (let bz = -WORLD + BLOCK / 2; bz < WORLD; bz += BLOCK) {
      // Skip city centre (drone spawn)
      if (Math.abs(bx) < 60 && Math.abs(bz) < 60) continue;

      // 1–4 buildings per block
      const count = 1 + Math.floor(srand() * 3);
      const footW = (BLOCK - GAP * 2) / count;

      for (let i = 0; i < count; i++) {
        const w = footW * (0.55 + srand() * 0.45) - GAP;
        const d = (BLOCK - GAP * 2) * (0.4 + srand() * 0.55);
        const h = 6 + Math.pow(srand(), 1.5) * 220;

        const geo = new THREE.BoxGeometry(w, h, d);
        const col = BUILDING_COLORS[Math.floor(srand() * BUILDING_COLORS.length)];
        const mat = new THREE.MeshLambertMaterial({ color: col });
        const mesh = new THREE.Mesh(geo, mat);

        const ox = bx - (BLOCK - GAP * 2) / 2 + footW * i + footW / 2 + (srand() - 0.5) * 4;
        const oz = bz + (srand() - 0.5) * (BLOCK * 0.3);
        mesh.position.set(ox, h / 2, oz);
        mesh.castShadow = true;
        mesh.receiveShadow = true;
        scene.add(mesh);
        buildingMeshes.push({ mesh, h, ox, oz, w, d });

        // Windows — canvas texture per building
        addWindows(mesh, w, h, d, srand);

        // Rooftop details
        if (h > 80 && srand() > 0.4) addRooftop(mesh, w, h, d, srand);
      }
    }
  }
}

function addWindows(parent, w, h, d, r) {
  // Create a simple emissive panel on the facade
  const cols = Math.max(1, Math.floor(w / 6));
  const rows = Math.max(1, Math.floor(h / 8));
  const ww = w / cols * 0.45;
  const wh = 3.5;

  const geo = new THREE.PlaneGeometry(ww, wh);
  const winColor = WINDOW_COLORS[Math.floor(r() * WINDOW_COLORS.length)];
  const mat = new THREE.MeshBasicMaterial({ color: winColor, transparent: true, opacity: 0.8 });

  for (let c = 0; c < cols; c++) {
    for (let row = 0; row < rows; row++) {
      if (r() > 0.65) continue; // dark windows
      const wx = -w / 2 + (c + 0.5) * (w / cols);
      const wy = -h / 2 + (row + 0.5) * (h / rows) + 1;

      // Front
      const mf = new THREE.Mesh(geo, mat);
      mf.position.set(wx, wy, d / 2 + 0.05);
      parent.add(mf);
      // Back
      const mb = mf.clone();
      mb.position.z = -d / 2 - 0.05;
      mb.rotation.y = Math.PI;
      parent.add(mb);
    }
  }
}

function addRooftop(parent, w, h, d, r) {
  // Small antenna / water tower
  if (r() > 0.5) {
    const ag = new THREE.CylinderGeometry(0.3, 0.3, 8 + r() * 15, 6);
    const am = new THREE.MeshLambertMaterial({ color: 0x444444 });
    const a  = new THREE.Mesh(ag, am);
    a.position.set((r() - 0.5) * w * 0.6, h / 2 + 6, (r() - 0.5) * d * 0.6);
    parent.add(a);
    // Red blink light
    const lg = new THREE.SphereGeometry(0.5, 6, 6);
    const lm = new THREE.MeshBasicMaterial({ color: 0xff2200 });
    const lh = new THREE.Mesh(lg, lm);
    lh.position.copy(a.position);
    lh.position.y += 4;
    lh.userData.blinkLight = true;
    parent.add(lh);
  }
  // HVAC box
  const hg = new THREE.BoxGeometry(r() * 6 + 2, r() * 3 + 1, r() * 6 + 2);
  const hm = new THREE.MeshLambertMaterial({ color: 0x222a33 });
  const hv = new THREE.Mesh(hg, hm);
  hv.position.set((r() - 0.5) * w * 0.5, h / 2 + 1, (r() - 0.5) * d * 0.5);
  parent.add(hv);
}

buildCity();

// Street lamps
(function buildLamps() {
  const postMat = new THREE.MeshLambertMaterial({ color: 0x333333 });
  const glowMat = new THREE.MeshBasicMaterial({ color: 0xffe0a0 });
  const SPACING = 40;
  for (let x = -WORLD; x <= WORLD; x += SPACING) {
    for (let z = -WORLD; z <= WORLD; z += SPACING) {
      const post = new THREE.Mesh(new THREE.CylinderGeometry(0.2, 0.2, 12, 5), postMat);
      post.position.set(x, 6, z);
      scene.add(post);
      const bulb = new THREE.Mesh(new THREE.SphereGeometry(0.6, 6, 6), glowMat);
      bulb.position.set(x, 12.5, z);
      scene.add(bulb);
      // Actual point light (a few only — performance)
      if (Math.abs(x) < 160 && Math.abs(z) < 160) {
        const pl = new THREE.PointLight(0xffe0a0, 0.5, 60);
        pl.position.set(x, 12, z);
        scene.add(pl);
      }
    }
  }
})();

// ── Raycaster for bullets ─────────────────────────────────────
const raycaster = new THREE.Raycaster();

// ── Enemy drone builder ───────────────────────────────────────
const ENEMY_TYPES = [
  { color: 0xff3344, hp: 1, speed: 14, score: 100, label: 'SCOUT',  scale: 1.0 },
  { color: 0xff8800, hp: 3, speed: 8,  score: 250, label: 'HEAVY',  scale: 1.6 },
  { color: 0xcc22ff, hp: 1, speed: 22, score: 350, label: 'SPEEDER',scale: 0.7 },
  { color: 0x00ccff, hp: 5, speed: 6,  score: 500, label: 'TANK',   scale: 2.2 },
];

function buildEnemyMesh(type) {
  const g = new THREE.Group();
  const s = type.scale;
  const col = type.color;

  // Body
  const bodyG = new THREE.BoxGeometry(2.4 * s, 0.5 * s, 2.4 * s);
  const bodyM = new THREE.MeshLambertMaterial({ color: col });
  g.add(new THREE.Mesh(bodyG, bodyM));

  // 4 arms
  const armG = new THREE.BoxGeometry(3 * s, 0.2 * s, 0.35 * s);
  const armM = new THREE.MeshLambertMaterial({ color: 0x222222 });
  const angles = [0, Math.PI / 2, Math.PI, -Math.PI / 2];
  angles.forEach(a => {
    const arm = new THREE.Mesh(armG, armM);
    arm.rotation.y = a;
    g.add(arm);
    // Rotor disc
    const rotG = new THREE.CylinderGeometry(0.9 * s, 0.9 * s, 0.1 * s, 12);
    const rotM = new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: 0.4 });
    const rot  = new THREE.Mesh(rotG, rotM);
    rot.position.set(Math.cos(a) * 1.5 * s, 0, Math.sin(a) * 1.5 * s);
    rot.userData.rotor = true;
    g.add(rot);
  });

  // Glow sphere
  const glowG = new THREE.SphereGeometry(0.6 * s, 8, 8);
  const glowM = new THREE.MeshBasicMaterial({ color: col });
  const glow  = new THREE.Mesh(glowG, glowM);
  glow.userData.glow = true;
  g.add(glow);

  return g;
}

// ── Game state ────────────────────────────────────────────────
let gs = {};
let running = false;
let paused  = false;
let lastTs  = 0;
const clock = new THREE.Clock();

// Pointer lock
let pitch = 0, yaw = 0;

document.addEventListener('pointerlockchange', () => {
  if (document.pointerLockElement !== renderer.domElement) {
    if (running && !paused) pauseGame();
  }
});

function lockPointer() { renderer.domElement.requestPointerLock(); }

document.addEventListener('mousemove', e => {
  if (!running || paused) return;
  yaw   -= e.movementX * 0.0018;
  pitch -= e.movementY * 0.0018;
  pitch  = Math.max(-1.2, Math.min(1.2, pitch));
});

// ── Input ─────────────────────────────────────────────────────
const keys = {};
window.addEventListener('keydown', e => {
  keys[e.code] = true;
  if (e.code === 'Escape' && running) {
    paused ? resumeGame() : pauseGame();
  }
  if (e.code === 'KeyR' && running && !paused) {
    if (!gs.reloading && gs.ammo < 30) startReload();
  }
  e.code === 'Space' && e.preventDefault();
});
window.addEventListener('keyup', e => { keys[e.code] = false; });

window.addEventListener('mousedown', e => {
  if (!running || paused) return;
  if (document.pointerLockElement !== renderer.domElement) { lockPointer(); return; }
  if (e.button === 0) shoot();
});

// ── Shoot ─────────────────────────────────────────────────────
const BULLET_SPEED  = 280;
const MAX_AMMO      = 30;
const RELOAD_MS     = 2000;
let   shootCooldown = 0;

const bulletGeo = new THREE.SphereGeometry(0.15, 6, 6);
const bulletMat = new THREE.MeshBasicMaterial({ color: 0xffee44 });
// Bullet trail
const trailMat  = new THREE.LineBasicMaterial({ color: 0xff8800, transparent: true, opacity: 0.6 });

function shoot() {
  if (gs.reloading || gs.ammo <= 0 || shootCooldown > 0) return;

  // direction from camera
  const dir = new THREE.Vector3(0, 0, -1).applyQuaternion(camera.quaternion);
  const origin = camera.position.clone().addScaledVector(dir, 1);

  // Raycast against enemies
  raycaster.set(origin, dir);
  const targets = gs.enemies.map(e => e.group);
  const hits    = raycaster.intersectObjects(targets, true);

  let hitEnemy = null;
  if (hits.length > 0) {
    // walk up to find which enemy group was hit
    let obj = hits[0].object;
    while (obj.parent && !obj.userData.enemyRef) obj = obj.parent;
    if (obj.userData.enemyRef) hitEnemy = obj.userData.enemyRef;
  }

  // Spawn visual bullet
  const b = new THREE.Mesh(bulletGeo, bulletMat);
  b.position.copy(origin);
  b.userData.velocity = dir.clone().multiplyScalar(BULLET_SPEED);
  b.userData.life     = 2.5; // seconds
  // Trail points
  const trailGeo = new THREE.BufferGeometry().setFromPoints([origin, origin.clone()]);
  const trail    = new THREE.Line(trailGeo, trailMat);
  scene.add(trail);
  b.userData.trail = trail;
  b.userData.prev  = origin.clone();
  scene.add(b);
  gs.bullets.push(b);

  if (hitEnemy) {
    damageEnemy(hitEnemy, 1);
    showHitMarker();
  }

  gs.ammo--;
  shootCooldown = 0.12;
  updateHUD();
  if (gs.ammo <= 0) startReload();
}

function startReload() {
  if (gs.reloading) return;
  gs.reloading = true;
  gs.reloadStart = performance.now();
  reloadWrap.classList.remove('hidden');
  updateHUD();
}

// ── Enemy logic ───────────────────────────────────────────────
const SPAWN_RADIUS = 300;

function spawnEnemy(typeOverride) {
  const waveScale = 1 + gs.wave * 0.08;
  const pool = gs.wave <= 1 ? [0] : gs.wave <= 2 ? [0,1] : gs.wave <= 4 ? [0,1,2] : [0,1,2,3];
  const type = typeOverride !== undefined ? ENEMY_TYPES[typeOverride]
    : ENEMY_TYPES[pool[Math.floor(Math.random() * pool.length)]];

  const angle  = Math.random() * Math.PI * 2;
  const radius = SPAWN_RADIUS + Math.random() * 60;
  const height = 30 + Math.random() * 120;

  const group = buildEnemyMesh(type);
  group.position.set(
    gs.drone.position.x + Math.cos(angle) * radius,
    height,
    gs.drone.position.z + Math.sin(angle) * radius
  );
  group.userData.enemyRef = null; // filled below

  const enemy = {
    group,
    type,
    hp:     type.hp,
    speed:  type.speed * waveScale,
    score:  type.score,
    alive:  true,
    vel:    new THREE.Vector3(),
    rotorT: 0,
    shootT: 3 + Math.random() * 4,  // seconds until first shot
    hitFlash: 0,
  };
  group.userData.enemyRef = enemy;
  scene.add(group);
  gs.enemies.push(enemy);
  return enemy;
}

function damageEnemy(enemy, dmg) {
  enemy.hp -= dmg;
  enemy.hitFlash = 0.12;
  if (enemy.hp <= 0) killEnemy(enemy);
}

function killEnemy(enemy) {
  enemy.alive = false;
  spawnExplosion(enemy.group.position.clone(), 0xff6622);
  scene.remove(enemy.group);
  gs.score  += enemy.score * gs.wave;
  gs.kills++;
  updateHUD();
}

// ── Explosions ────────────────────────────────────────────────
const PARTICLE_POOL = [];
const MAX_PARTICLES = 200;
(function buildPool() {
  const g = new THREE.SphereGeometry(0.3, 4, 4);
  for (let i = 0; i < MAX_PARTICLES; i++) {
    const m = new THREE.MeshBasicMaterial({ color: 0xff4400 });
    const p = new THREE.Mesh(g, m);
    p.userData.active = false;
    PARTICLE_POOL.push(p);
  }
})();

function spawnExplosion(pos, color) {
  for (let i = 0; i < 24; i++) {
    const p = PARTICLE_POOL.find(p => !p.userData.active);
    if (!p) break;
    p.userData.active = true;
    p.userData.vel = new THREE.Vector3(
      (Math.random() - 0.5) * 20,
      Math.random() * 14,
      (Math.random() - 0.5) * 20
    );
    p.userData.life    = 0.5 + Math.random() * 0.6;
    p.userData.maxLife = p.userData.life;
    p.material.color.setHex(color);
    p.position.copy(pos);
    p.scale.setScalar(0.6 + Math.random() * 1.2);
    scene.add(p);
  }
}

function tickParticles(dt) {
  PARTICLE_POOL.forEach(p => {
    if (!p.userData.active) return;
    p.userData.life -= dt;
    if (p.userData.life <= 0) { p.userData.active = false; scene.remove(p); return; }
    p.position.addScaledVector(p.userData.vel, dt);
    p.userData.vel.y -= 9 * dt;
    const a = p.userData.life / p.userData.maxLife;
    p.scale.setScalar(a * 1.2);
    p.material.opacity = a;
    p.material.transparent = true;
  });
}

// ── Enemy bullets ─────────────────────────────────────────────
const enemyBulletGeo = new THREE.SphereGeometry(0.3, 6, 6);
const enemyBulletMat = new THREE.MeshBasicMaterial({ color: 0xff2200 });

function spawnEnemyBullet(enemy) {
  const dir = new THREE.Vector3().subVectors(gs.drone.position, enemy.group.position).normalize();
  const b   = new THREE.Mesh(enemyBulletGeo, enemyBulletMat.clone());
  b.position.copy(enemy.group.position).addScaledVector(dir, 3);
  b.userData.vel  = dir.multiplyScalar(60);
  b.userData.life = 5;
  b.userData.enemy = true;
  scene.add(b);
  gs.enemyBullets.push(b);
}

// ── Drone model (visible in mirrors / third person — just used for shadow) ──
const dronePivot = new THREE.Group();

(function buildPlayerDrone() {
  const bodyG = new THREE.BoxGeometry(1.2, 0.35, 1.2);
  const bodyM = new THREE.MeshLambertMaterial({ color: 0x334455 });
  const body  = new THREE.Mesh(bodyG, bodyM);
  body.castShadow = true;
  dronePivot.add(body);

  const armG = new THREE.BoxGeometry(2.8, 0.15, 0.25);
  const armM = new THREE.MeshLambertMaterial({ color: 0x222233 });
  [0, Math.PI/2, Math.PI, -Math.PI/2].forEach(a => {
    const arm = new THREE.Mesh(armG, armM);
    arm.rotation.y = a;
    arm.castShadow = true;
    dronePivot.add(arm);
  });
})();

scene.add(dronePivot);

// ── Wave management ───────────────────────────────────────────
function startWave() {
  const count = 6 + (gs.wave - 1) * 4;
  for (let i = 0; i < count; i++) spawnEnemy();
  showBanner('WAVE  ' + gs.wave, 2200);
  updateHUD();
}

function checkWaveDone() {
  if (gs.enemies.filter(e => e.alive).length === 0 && !gs.wavePending) {
    gs.wavePending = true;
    showBanner('WAVE ' + gs.wave + '  CLEAR', 2000);
    setTimeout(() => {
      gs.wave++;
      gs.wavePending = false;
      startWave();
    }, 3000);
  }
}

function showBanner(txt, dur) {
  waveBanner.textContent = txt;
  waveBanner.classList.add('show');
  waveBanner.classList.remove('hidden');
  setTimeout(() => waveBanner.classList.remove('show'), dur);
}

// ── HUD update ────────────────────────────────────────────────
const MAX_HP = 100;
function updateHUD() {
  elScore.textContent  = gs.score;
  elWave.textContent   = gs.wave;
  elKills.textContent  = gs.kills;
  elAmmo.textContent   = gs.reloading ? 'RELOADING...' : gs.ammo + ' / ' + MAX_AMMO;
  elAlt.textContent    = Math.round(gs.drone.position.y) + 'm';
  const hpPct = Math.max(0, gs.hp / MAX_HP * 100);
  elHealthB.style.width = hpPct + '%';
  if (hpPct < 25) elHealthB.style.background = '#ff2233';
  else if (hpPct < 60) elHealthB.style.background = 'linear-gradient(90deg,#ffaa00,#ffdd44)';
  else elHealthB.style.background = 'linear-gradient(90deg,#ff4455,#ff8866)';
}

function showHitMarker() {
  hitMarker.classList.remove('flash');
  void hitMarker.offsetWidth;
  hitMarker.classList.add('flash');
}

// ── Init & restart ────────────────────────────────────────────
function initGame() {
  // Clean old enemies / bullets
  if (gs.enemies) {
    gs.enemies.forEach(e => scene.remove(e.group));
    gs.bullets && gs.bullets.forEach(b => { scene.remove(b); scene.remove(b.userData.trail); });
    gs.enemyBullets && gs.enemyBullets.forEach(b => scene.remove(b));
  }

  pitch = 0; yaw = 0;

  gs = {
    drone: camera, // camera IS the drone
    hp: MAX_HP,
    ammo: MAX_AMMO,
    reloading: false,
    reloadStart: 0,
    score: 0,
    kills: 0,
    wave:  1,
    wavePending: false,
    enemies:      [],
    bullets:      [],
    enemyBullets: [],
    invincible:   0,
  };

  camera.position.set(0, 55, 0);
  camera.rotation.set(0, 0, 0);
  camera.quaternion.identity();

  overlay.classList.add('hidden');
  gameoverEl.classList.add('hidden');
  updateHUD();
  startWave();
}

// ── Pause ─────────────────────────────────────────────────────
function pauseGame() {
  paused = true;
  pausedEl.classList.remove('hidden');
  document.exitPointerLock();
}
function resumeGame() {
  paused = false;
  pausedEl.classList.add('hidden');
  lockPointer();
}
pausedEl.addEventListener('click', () => { if (paused) resumeGame(); });

// ── Game over ─────────────────────────────────────────────────
function endGame() {
  running = false;
  document.exitPointerLock();
  goScore.textContent = gs.score;
  goWave.textContent  = gs.wave;
  goKills.textContent = gs.kills;
  gameoverEl.classList.remove('hidden');
}

// ── Drone physics ─────────────────────────────────────────────
const MOVE_SPEED   = 22;
const BOOST_MULTI  = 2.4;
const ACCEL        = 18;
const DRAG         = 0.88;

const droneVel = new THREE.Vector3();
const _fwd = new THREE.Vector3();
const _right = new THREE.Vector3();
const _up = new THREE.Vector3(0, 1, 0);

function tickDrone(dt) {
  const boost = keys['KeyF'];
  const spd   = MOVE_SPEED * (boost ? BOOST_MULTI : 1);

  // Get camera directions (flatten vertical for strafing)
  _fwd.set(0, 0, -1).applyQuaternion(camera.quaternion);
  _fwd.y = 0; _fwd.normalize();
  _right.crossVectors(_fwd, _up).normalize();

  const accel = new THREE.Vector3();
  if (keys['KeyW'] || keys['ArrowUp'])    accel.addScaledVector(_fwd, 1);
  if (keys['KeyS'] || keys['ArrowDown'])  accel.addScaledVector(_fwd, -1);
  if (keys['KeyA'] || keys['ArrowLeft'])  accel.addScaledVector(_right, -1);
  if (keys['KeyD'] || keys['ArrowRight']) accel.addScaledVector(_right, 1);
  if (keys['Space'])  accel.y += 1;
  if (keys['ShiftLeft'] || keys['ShiftRight']) accel.y -= 1;

  if (accel.length() > 0) accel.normalize().multiplyScalar(ACCEL * spd * dt);
  droneVel.add(accel);
  droneVel.multiplyScalar(DRAG);

  // Q/E yaw without mouse
  if (keys['KeyQ']) yaw += dt * 1.4;
  if (keys['KeyE']) yaw -= dt * 1.4;

  camera.position.addScaledVector(droneVel, dt);

  // Floor clamp
  if (camera.position.y < 4) { camera.position.y = 4; droneVel.y = 0; }
  if (camera.position.y > 600) { camera.position.y = 600; droneVel.y = 0; }

  // Apply look rotation
  const qYaw   = new THREE.Quaternion().setFromAxisAngle(_up, yaw);
  const qPitch = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), pitch);
  camera.quaternion.copy(qYaw).multiply(qPitch);

  // Sync drone shadow model
  dronePivot.position.copy(camera.position);
  dronePivot.quaternion.copy(qYaw);

  // Speed lines
  const spd2 = droneVel.length();
  if (spd2 > 6 || boost) speedlines.classList.add('active');
  else speedlines.classList.remove('active');

  gs.invincible = Math.max(0, gs.invincible - dt);
}

// ── Update bullets ────────────────────────────────────────────
function tickBullets(dt) {
  for (let i = gs.bullets.length - 1; i >= 0; i--) {
    const b = gs.bullets[i];
    b.userData.life -= dt;
    if (b.userData.life <= 0) {
      scene.remove(b);
      scene.remove(b.userData.trail);
      gs.bullets.splice(i, 1);
      continue;
    }
    b.position.addScaledVector(b.userData.vel, dt);
    // Update trail
    const pts = [b.userData.prev.clone(), b.position.clone()];
    b.userData.trail.geometry.setFromPoints(pts);
    b.userData.prev.copy(b.position);
  }
}

// ── Update enemy bullets ──────────────────────────────────────
function tickEnemyBullets(dt) {
  for (let i = gs.enemyBullets.length - 1; i >= 0; i--) {
    const b = gs.enemyBullets[i];
    b.userData.life -= dt;
    b.position.addScaledVector(b.userData.vel, dt);
    const dist = b.position.distanceTo(camera.position);
    if (b.userData.life <= 0 || dist > 500) {
      scene.remove(b);
      gs.enemyBullets.splice(i, 1);
      continue;
    }
    if (dist < 5 && gs.invincible <= 0) {
      scene.remove(b);
      gs.enemyBullets.splice(i, 1);
      gs.hp -= 12;
      gs.invincible = 1.5;
      vignette.classList.remove('hit');
      void vignette.offsetWidth;
      vignette.classList.add('hit');
      updateHUD();
      if (gs.hp <= 0) { endGame(); return; }
    }
  }
}

// ── Update enemies ────────────────────────────────────────────
function tickEnemies(dt) {
  for (let i = gs.enemies.length - 1; i >= 0; i--) {
    const e = gs.enemies[i];
    if (!e.alive) { gs.enemies.splice(i, 1); continue; }

    // Steer toward drone
    const toPlayer = new THREE.Vector3().subVectors(camera.position, e.group.position);
    const dist = toPlayer.length();
    toPlayer.normalize();

    // Slight hover wobble
    e.group.position.y += Math.sin(Date.now() * 0.002 + i) * 0.04;

    // Move
    e.vel.addScaledVector(toPlayer, e.speed * 2 * dt);
    e.vel.multiplyScalar(0.92);
    e.group.position.addScaledVector(e.vel, dt);

    // Face player
    e.group.lookAt(camera.position);

    // Rotor spin
    e.rotorT += dt * 8;
    e.group.children.forEach(c => {
      if (c.userData.rotor) c.rotation.y = e.rotorT;
    });

    // Hit flash
    if (e.hitFlash > 0) {
      e.hitFlash -= dt;
      e.group.children.forEach(c => { if (c.material) c.material.emissive && c.material.emissive.setHex(0xffffff); });
    } else {
      e.group.children.forEach(c => { if (c.material && c.material.emissive) c.material.emissive.setHex(0x000000); });
    }

    // Glow pulse
    e.group.children.forEach(c => {
      if (c.userData.glow) {
        const pulse = 0.5 + 0.5 * Math.sin(Date.now() * 0.004);
        c.scale.setScalar(0.8 + pulse * 0.4);
      }
    });

    // Ram damage
    if (dist < 4 && gs.invincible <= 0) {
      gs.hp -= 20;
      gs.invincible = 2;
      vignette.classList.remove('hit');
      void vignette.offsetWidth;
      vignette.classList.add('hit');
      spawnExplosion(e.group.position.clone(), 0xff6622);
      e.alive = false;
      scene.remove(e.group);
      gs.enemies.splice(i, 1);
      gs.kills++;
      gs.score += e.score;
      updateHUD();
      if (gs.hp <= 0) { endGame(); return; }
      continue;
    }

    // Enemy shooting
    e.shootT -= dt;
    if (e.shootT <= 0 && dist < 200) {
      spawnEnemyBullet(e);
      e.shootT = 2 + Math.random() * 3;
    }
  }
}

// ── Reload tick ───────────────────────────────────────────────
function tickReload() {
  if (!gs.reloading) return;
  const pct = Math.min(1, (performance.now() - gs.reloadStart) / RELOAD_MS);
  reloadFill.style.width = (pct * 100) + '%';
  if (pct >= 1) {
    gs.reloading = false;
    gs.ammo = MAX_AMMO;
    reloadWrap.classList.add('hidden');
    updateHUD();
  }
}

// ── Blink lights ──────────────────────────────────────────────
let blinkT = 0;
function tickBlinks(dt) {
  blinkT += dt;
  const on = Math.sin(blinkT * 2.5) > 0;
  // Find all blink meshes — expensive so only every ~5 frames
  // (handled lazily, skip for performance in large scene)
}

// ── Main loop ─────────────────────────────────────────────────
function loop(ts) {
  if (!running) return;
  const dt = Math.min((ts - lastTs) / 1000, 0.05);
  lastTs = ts;

  if (!paused) {
    shootCooldown -= dt;
    tickDrone(dt);
    tickBullets(dt);
    tickEnemyBullets(dt);
    tickEnemies(dt);
    tickParticles(dt);
    tickReload();
    checkWaveDone();
    updateHUD();
  }

  renderer.render(scene, camera);
  requestAnimationFrame(loop);
}

// ── Start ─────────────────────────────────────────────────────
document.getElementById('startBtn').addEventListener('click', () => {
  overlay.classList.add('hidden');
  initGame();
  running = true;
  lastTs  = performance.now();
  lockPointer();
  requestAnimationFrame(loop);
});

document.getElementById('restartBtn').addEventListener('click', () => {
  gameoverEl.classList.add('hidden');
  initGame();
  running = true;
  lastTs  = performance.now();
  lockPointer();
  requestAnimationFrame(loop);
});

// Idle preview render
(function idleRender() {
  if (running) return;
  renderer.render(scene, camera);
  requestAnimationFrame(idleRender);
})();
