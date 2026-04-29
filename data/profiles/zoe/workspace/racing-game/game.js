(() => {
  // ========== TRACK DEFINITION ==========
  // Track is a loop of waypoints. Karts follow the spline.
  const TRACK_PTS = [
    {x:0, z:0}, {x:60, z:-10}, {x:110, z:-50}, {x:120, z:-110},
    {x:100, z:-160}, {x:50, z:-180}, {x:-10, z:-170}, {x:-50, z:-140},
    {x:-80, z:-90}, {x:-70, z:-30}, {x:-40, z:10}, {x:0, z:0}
  ];

  // Subdivide track into smooth path
  function subdivide(pts, res) {
    const out = [];
    for (let i = 0; i < pts.length - 1; i++) {
      const a = pts[i], b = pts[(i+1) % pts.length];
      const c = pts[(i+2) % pts.length];
      const d = pts[(i-1+pts.length) % pts.length];
      for (let t = 0; t < 1; t += 1/res) {
        // Catmull-Rom
        const t2 = t*t, t3 = t2*t;
        const x = 0.5*((-d.x+3*a.x-3*b.x+c.x)*t3 + (2*d.x-5*a.x+4*b.x-c.x)*t2 + (-d.x+b.x)*t + 2*a.x);
        const z = 0.5*((-d.z+3*a.z-3*b.z+c.z)*t3 + (2*d.z-5*a.z+4*b.z-c.z)*t2 + (-d.z+b.z)*t + 2*a.z);
        out.push({x, z});
      }
    }
    return out;
  }
  const track = subdivide(TRACK_PTS, 30);
  const TRACK_LEN = track.length;

  // Compute cumulative distance and tangent for each track point
  const trackDist = [0];
  const trackTan = [];
  for (let i = 1; i < TRACK_LEN; i++) {
    const dx = track[i].x - track[i-1].x;
    const dz = track[i].z - track[i-1].z;
    trackDist.push(trackDist[i-1] + Math.sqrt(dx*dx + dz*dz));
  }
  const totalTrackLen = trackDist[TRACK_LEN - 1];
  for (let i = 0; i < TRACK_LEN; i++) {
    const n = (i+1) % TRACK_LEN;
    const dx = track[n].x - track[i].x;
    const dz = track[n].z - track[i].z;
    const len = Math.sqrt(dx*dx + dz*dz) || 1;
    trackTan.push({x: dx/len, z: dz/len});
  }

  // Find closest track index to a world position
  function closestTrackIdx(px, pz) {
    let best = 0, bestD = 1e9;
    for (let i = 0; i < TRACK_LEN; i++) {
      const dx = track[i].x - px, dz = track[i].z - pz;
      const d = dx*dx + dz*dz;
      if (d < bestD) { bestD = d; best = i; }
    }
    return best;
  }

  // ========== THREE.JS SETUP ==========
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x1a0a2e);
  scene.fog = new THREE.Fog(0x1a0a2e, 80, 250);

  const camera = new THREE.PerspectiveCamera(65, innerWidth/innerHeight, 0.1, 500);
  const renderer = new THREE.WebGLRenderer({antialias: true});
  renderer.setSize(innerWidth, innerHeight);
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;
  document.body.prepend(renderer.domElement);

  window.addEventListener('resize', () => {
    camera.aspect = innerWidth/innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(innerWidth, innerHeight);
  });

  // Lighting
  scene.add(new THREE.AmbientLight(0x667799, 0.7));
  const sun = new THREE.DirectionalLight(0xffeedd, 0.9);
  sun.position.set(40, 60, 30);
  sun.castShadow = true;
  scene.add(sun);
  scene.add(new THREE.HemisphereLight(0x4488ff, 0x002211, 0.3));

  // ========== BUILD TRACK MESH ==========
  const ROAD_W = 12;
  function buildTrackMesh() {
    // Ground plane
    const ground = new THREE.Mesh(
      new THREE.PlaneGeometry(600, 600),
      new THREE.MeshStandardMaterial({color: 0x0a1a0a, roughness:1})
    );
    ground.rotation.x = -Math.PI/2;
    ground.position.set(20, -0.1, -90);
    ground.receiveShadow = true;
    scene.add(ground);

    // Road surface as triangle strip
    const roadVerts = [], roadIdx = [];
    for (let i = 0; i < TRACK_LEN; i++) {
      const p = track[i];
      const t = trackTan[i];
      // Normal = perpendicular to tangent
      const nx = -t.z, nz = t.x;
      roadVerts.push(p.x + nx*ROAD_W/2, 0, p.z + nz*ROAD_W/2);
      roadVerts.push(p.x - nx*ROAD_W/2, 0, p.z - nz*ROAD_W/2);
      if (i < TRACK_LEN - 1) {
        const a = i*2, b = i*2+1, c = (i+1)*2, d = (i+1)*2+1;
        roadIdx.push(a,c,b, b,c,d);
      }
    }
    const roadGeo = new THREE.BufferGeometry();
    roadGeo.setAttribute('position', new THREE.Float32BufferAttribute(roadVerts, 3));
    roadGeo.setIndex(roadIdx);
    roadGeo.computeVertexNormals();
    const road = new THREE.Mesh(roadGeo, new THREE.MeshStandardMaterial({color:0x333344, roughness:0.7}));
    road.receiveShadow = true;
    scene.add(road);

    // Edge neon strips + barriers
    for (const side of [-1, 1]) {
      const edgeGeo = new THREE.BufferGeometry();
      const ev = [], ei = [];
      for (let i = 0; i < TRACK_LEN; i++) {
        const p = track[i], t = trackTan[i];
        const nx = -t.z * side, nz = t.x * side;
        ev.push(p.x + nx*ROAD_W/2, 0, p.z + nz*ROAD_W/2);
        ev.push(p.x + nx*ROAD_W/2, 0.6, p.z + nz*ROAD_W/2);
        if (i < TRACK_LEN - 1) {
          const a = i*2, b = i*2+1, c = (i+1)*2, d = (i+1)*2+1;
          ei.push(a,c,b, b,c,d);
        }
      }
      edgeGeo.setAttribute('position', new THREE.Float32BufferAttribute(ev, 3));
      edgeGeo.setIndex(ei);
      edgeGeo.computeVertexNormals();
      const color = side === -1 ? 0x00ffff : 0xff00ff;
      const edge = new THREE.Mesh(edgeGeo, new THREE.MeshBasicMaterial({color}));
      scene.add(edge);
    }

    // Dashed center line
    for (let i = 0; i < TRACK_LEN; i += 6) {
      if ((Math.floor(i/3)) % 2 === 0) continue;
      const p = track[i], n = (i+2) % TRACK_LEN;
      const p2 = track[n];
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.Float32BufferAttribute([
        p.x, 0.02, p.z, p2.x, 0.02, p2.z
      ], 3));
      const line = new THREE.Line(geo, new THREE.LineBasicMaterial({color:0x666688}));
      scene.add(line);
    }

    // Start/finish line
    const sf = track[0], sfn = trackTan[0];
    const sfMesh = new THREE.Mesh(
      new THREE.PlaneGeometry(ROAD_W, 2),
      new THREE.MeshBasicMaterial({color:0xffffff, side: THREE.DoubleSide})
    );
    sfMesh.rotation.x = -Math.PI/2;
    sfMesh.rotation.z = Math.atan2(sfn.x, sfn.z);
    sfMesh.position.set(sf.x, 0.05, sf.z);
    scene.add(sfMesh);

    // Checkerboard on start line
    for (let i = 0; i < 6; i++) {
      for (let j = 0; j < 2; j++) {
        if ((i+j) % 2 === 0) continue;
        const sq = new THREE.Mesh(
          new THREE.PlaneGeometry(ROAD_W/6, 1),
          new THREE.MeshBasicMaterial({color:0x000000})
        );
        sq.rotation.x = -Math.PI/2;
        sq.rotation.z = Math.atan2(sfn.x, sfn.z);
        const nx = -sfn.z, nz = sfn.x;
        const offset = (i - 2.5) * ROAD_W/6;
        sq.position.set(sf.x + nx*offset, 0.06, sf.z + nz*offset + (j-0.5));
        scene.add(sq);
      }
    }

    // Scenery: trees and buildings
    for (let i = 0; i < TRACK_LEN; i += 8) {
      for (const side of [-1, 1]) {
        const p = track[i], t = trackTan[i];
        const nx = -t.z * side, nz = t.x * side;
        const dist = ROAD_W/2 + 8 + Math.random() * 20;
        const wx = p.x + nx * dist;
        const wz = p.z + nz * dist;
        if (Math.random() > 0.5) {
          // Tree
          const trunk = new THREE.Mesh(
            new THREE.CylinderGeometry(0.3, 0.4, 3, 6),
            new THREE.MeshStandardMaterial({color:0x4a3520})
          );
          trunk.position.set(wx, 1.5, wz);
          trunk.castShadow = true;
          scene.add(trunk);
          const leaves = new THREE.Mesh(
            new THREE.SphereGeometry(2, 6, 6),
            new THREE.MeshStandardMaterial({color: 0x005500 + Math.floor(Math.random()*0x003300)})
          );
          leaves.position.set(wx, 4, wz);
          leaves.castShadow = true;
          scene.add(leaves);
        } else {
          // Building
          const h = 4 + Math.random() * 15;
          const bld = new THREE.Mesh(
            new THREE.BoxGeometry(3+Math.random()*4, h, 3+Math.random()*4),
            new THREE.MeshStandardMaterial({color:0x1a1a2e, emissive:0x111128})
          );
          bld.position.set(wx, h/2, wz);
          bld.castShadow = true;
          scene.add(bld);
        }
      }
    }

    // Stars
    const sv = [];
    for (let i = 0; i < 600; i++) sv.push((Math.random()-0.5)*500, 50+Math.random()*80, (Math.random()-0.5)*500);
    const sg = new THREE.BufferGeometry();
    sg.setAttribute('position', new THREE.Float32BufferAttribute(sv, 3));
    scene.add(new THREE.Points(sg, new THREE.PointsMaterial({color:0xffffff, size:0.3})));
  }
  buildTrackMesh();

  // ========== KART ==========
  const KART_COLORS = [0x00ccff, 0xff2244, 0x44ff22, 0xffaa00, 0xff44ff, 0xffffff];
  const KART_NAMES = ['YOU', 'RED', 'GREEN', 'ORANGE', 'PINK', 'WHITE'];

  function createKart(color) {
    const g = new THREE.Group();
    // Body
    const body = new THREE.Mesh(
      new THREE.BoxGeometry(1.6, 0.5, 2.8),
      new THREE.MeshStandardMaterial({color, metalness:0.6, roughness:0.25})
    );
    body.position.y = 0.45;
    body.castShadow = true;
    g.add(body);
    // Head (driver)
    const head = new THREE.Mesh(
      new THREE.SphereGeometry(0.35, 8, 8),
      new THREE.MeshStandardMaterial({color:0xffcc88})
    );
    head.position.set(0, 1.1, -0.2);
    g.add(head);
    // Helmet
    const helmet = new THREE.Mesh(
      new THREE.SphereGeometry(0.38, 8, 8, 0, Math.PI*2, 0, Math.PI/2),
      new THREE.MeshStandardMaterial({color})
    );
    helmet.position.set(0, 1.15, -0.2);
    g.add(helmet);
    // Wheels
    const wg = new THREE.CylinderGeometry(0.25, 0.25, 0.18, 10);
    const wm = new THREE.MeshStandardMaterial({color:0x222222});
    [[-0.8,0.25,0.9],[0.8,0.25,0.9],[-0.8,0.25,-0.9],[0.8,0.25,-0.9]].forEach(p => {
      const w = new THREE.Mesh(wg, wm);
      w.rotation.z = Math.PI/2;
      w.position.set(...p);
      g.add(w);
    });
    // Underglow
    const glow = new THREE.PointLight(color, 1.5, 5);
    glow.position.set(0, 0.2, 0);
    g.add(glow);
    return g;
  }

  // ========== ITEM BOXES ON TRACK ==========
  const ITEM_TYPES = ['boost', 'banana', 'star'];
  const ITEM_EMOJI = {boost: '\u{1F680}', banana: '\u{1F34C}', star: '\u2B50'};
  const itemBoxes = [];
  const itemBoxMeshes = [];

  function spawnItemBoxes() {
    // Place item boxes at intervals around track
    for (let i = 30; i < TRACK_LEN - 30; i += Math.floor(TRACK_LEN / 8)) {
      const p = track[i], t = trackTan[i];
      for (const offset of [-ROAD_W/4, 0, ROAD_W/4]) {
        const nx = -t.z, nz = t.x;
        const box = new THREE.Mesh(
          new THREE.BoxGeometry(1.2, 1.2, 1.2),
          new THREE.MeshStandardMaterial({color: 0xffff00, emissive: 0x886600, transparent: true, opacity: 0.7})
        );
        box.position.set(p.x + nx*offset, 1, p.z + nz*offset);
        box.userData = {trackIdx: i, alive: true};
        scene.add(box);
        itemBoxMeshes.push(box);
        itemBoxes.push(box);
      }
    }
  }
  spawnItemBoxes();

  // ========== RACERS ==========
  const TOTAL_LAPS = 3;
  const NUM_AI = 5;

  class Racer {
    constructor(idx, isPlayer) {
      this.idx = idx;
      this.isPlayer = isPlayer;
      this.mesh = createKart(KART_COLORS[idx]);
      scene.add(this.mesh);
      this.trackPos = 0; // float position along track array
      this.speed = 0;
      this.lap = 0;
      this.lastCheckIdx = 0;
      this.finished = false;
      this.finishTime = 0;
      this.lateralOffset = 0; // offset from center of track
      this.item = null;
      this.boostTimer = 0;
      this.starTimer = 0;
      this.spinTimer = 0;
      this.name = KART_NAMES[idx];
      // AI params
      this.aiSkill = 0.7 + Math.random() * 0.3;
      this.aiTargetOffset = (Math.random() - 0.5) * ROAD_W * 0.5;
      this.aiOffsetTimer = 0;
    }

    getWorldPos() {
      const i = Math.floor(this.trackPos) % TRACK_LEN;
      const f = this.trackPos - Math.floor(this.trackPos);
      const n = (i + 1) % TRACK_LEN;
      return {
        x: track[i].x + (track[n].x - track[i].x) * f,
        z: track[i].z + (track[n].z - track[i].z) * f
      };
    }

    getHeading() {
      const i = Math.floor(this.trackPos) % TRACK_LEN;
      return Math.atan2(trackTan[i].x, trackTan[i].z);
    }

    totalProgress() {
      return this.lap * TRACK_LEN + this.trackPos;
    }
  }

  let racers = [];
  let player;

  function initRacers() {
    racers.forEach(r => scene.remove(r.mesh));
    racers = [];
    for (let i = 0; i <= NUM_AI; i++) {
      const r = new Racer(i, i === 0);
      // Stagger start positions
      r.trackPos = TRACK_LEN - 5 - i * 8;
      r.lateralOffset = (i % 2 === 0 ? -1 : 1) * 2;
      racers.push(r);
      if (i === 0) player = r;
    }
  }

  // ========== BANANAS ON TRACK ==========
  const bananas = [];
  function spawnBanana(x, z) {
    const mesh = new THREE.Mesh(
      new THREE.SphereGeometry(0.4, 6, 6),
      new THREE.MeshStandardMaterial({color: 0xffdd00})
    );
    mesh.position.set(x, 0.4, z);
    scene.add(mesh);
    bananas.push({mesh, x, z, life: 15});
  }

  // ========== GAME STATE ==========
  let gameState = 'menu'; // menu, countdown, racing, finished
  let raceTime = 0;
  const keys = {};
  window.addEventListener('keydown', e => { keys[e.key.toLowerCase()] = true; e.preventDefault(); });
  window.addEventListener('keyup', e => { keys[e.key.toLowerCase()] = false; });

  const hudPos = document.getElementById('position');
  const hudLap = document.getElementById('lap');
  const hudSpeed = document.getElementById('speed');
  const hudItem = document.getElementById('item-box');
  const overlay = document.getElementById('overlay');
  const countdownEl = document.getElementById('countdown');
  const resultsEl = document.getElementById('results');
  const resultsTable = document.getElementById('resultsTable');
  const resultsTitle = document.getElementById('resultsTitle');

  // ========== PLAYER CONTROLS ==========
  const MAX_SPEED = 0.6;
  const BOOST_SPEED = 0.95;
  const AI_BASE_SPEED = 0.45;
  const ACCEL = 0.008;
  const BRAKE_FORCE = 0.015;
  const FRICTION_VAL = 0.003;
  const LATERAL_SPEED = 0.35;

  function updatePlayer(dt) {
    if (player.finished || player.spinTimer > 0) {
      if (player.spinTimer > 0) {
        player.spinTimer -= dt;
        player.speed *= 0.95;
      }
      return;
    }

    const up = keys['arrowup'] || keys['w'];
    const down = keys['arrowdown'] || keys['s'];
    const left = keys['arrowleft'] || keys['a'];
    const right = keys['arrowright'] || keys['d'];
    const useItem = keys[' '];

    const maxSpd = player.boostTimer > 0 ? BOOST_SPEED : MAX_SPEED;

    if (up) player.speed = Math.min(player.speed + ACCEL, maxSpd);
    else if (down) player.speed = Math.max(player.speed - BRAKE_FORCE, -0.15);
    else player.speed = Math.max(player.speed - FRICTION_VAL, 0);

    if (left) player.lateralOffset = Math.max(player.lateralOffset - LATERAL_SPEED, -ROAD_W/2 + 1.5);
    if (right) player.lateralOffset = Math.min(player.lateralOffset + LATERAL_SPEED, ROAD_W/2 - 1.5);

    player.trackPos += player.speed;
    if (player.trackPos >= TRACK_LEN) {
      player.trackPos -= TRACK_LEN;
      player.lap++;
      if (player.lap >= TOTAL_LAPS) {
        player.finished = true;
        player.finishTime = raceTime;
      }
    }

    if (player.boostTimer > 0) player.boostTimer -= dt;

    // Use item
    if (useItem && player.item) {
      activateItem(player);
      keys[' '] = false; // consume
    }
  }

  function activateItem(racer) {
    const item = racer.item;
    racer.item = null;
    if (item === 'boost') {
      racer.boostTimer = 2;
      racer.speed = Math.min(racer.speed + 0.3, BOOST_SPEED);
    } else if (item === 'banana') {
      // Drop banana behind
      const wp = racer.getWorldPos();
      const h = racer.getHeading();
      spawnBanana(wp.x - Math.sin(h)*4, wp.z - Math.cos(h)*4);
    } else if (item === 'star') {
      racer.starTimer = 4;
      racer.boostTimer = 4;
    }
  }

  // ========== AI ==========
  function updateAI(r, dt) {
    if (r.finished || r.spinTimer > 0) {
      if (r.spinTimer > 0) { r.spinTimer -= dt; r.speed *= 0.95; }
      return;
    }

    // Vary target speed by skill
    const baseSpeed = AI_BASE_SPEED * r.aiSkill;
    const maxSpd = r.boostTimer > 0 ? BOOST_SPEED * 0.9 : baseSpeed;

    // Rubber-banding: if far behind player, speed up
    const diff = player.totalProgress() - r.totalProgress();
    let rubberband = 0;
    if (diff > 50) rubberband = 0.08;
    else if (diff < -50) rubberband = -0.04;

    const targetSpeed = Math.min(maxSpd + rubberband, BOOST_SPEED);
    if (r.speed < targetSpeed) r.speed = Math.min(r.speed + ACCEL * 0.9, targetSpeed);
    else r.speed = Math.max(r.speed - FRICTION_VAL, targetSpeed * 0.8);

    r.trackPos += r.speed;
    if (r.trackPos >= TRACK_LEN) {
      r.trackPos -= TRACK_LEN;
      r.lap++;
      if (r.lap >= TOTAL_LAPS) {
        r.finished = true;
        r.finishTime = raceTime;
      }
    }

    // Lateral movement — gently swerve
    r.aiOffsetTimer -= dt;
    if (r.aiOffsetTimer <= 0) {
      r.aiTargetOffset = (Math.random() - 0.5) * ROAD_W * 0.5;
      r.aiOffsetTimer = 2 + Math.random() * 3;
    }
    const latDiff = r.aiTargetOffset - r.lateralOffset;
    r.lateralOffset += Math.sign(latDiff) * Math.min(Math.abs(latDiff), LATERAL_SPEED * 0.5);

    if (r.boostTimer > 0) r.boostTimer -= dt;
    if (r.starTimer > 0) r.starTimer -= dt;

    // AI uses items immediately
    if (r.item) activateItem(r);
  }

  // ========== COLLISIONS ==========
  function checkCollisions() {
    for (const r of racers) {
      if (r.finished) continue;
      const wp = r.getWorldPos();
      const i = Math.floor(r.trackPos) % TRACK_LEN;
      const tan = trackTan[i];
      const nx = -tan.z, nz = tan.x;
      const worldX = wp.x + nx * r.lateralOffset;
      const worldZ = wp.z + nz * r.lateralOffset;

      // Item box pickup
      for (const box of itemBoxMeshes) {
        if (!box.userData.alive) continue;
        const dx = worldX - box.position.x;
        const dz = worldZ - box.position.z;
        if (dx*dx + dz*dz < 3) {
          if (!r.item) {
            r.item = ITEM_TYPES[Math.floor(Math.random() * ITEM_TYPES.length)];
          }
          box.userData.alive = false;
          box.visible = false;
          // Respawn after delay
          setTimeout(() => { box.userData.alive = true; box.visible = true; }, 5000);
        }
      }

      // Banana collision
      for (let b = bananas.length - 1; b >= 0; b--) {
        const ban = bananas[b];
        const dx = worldX - ban.x, dz = worldZ - ban.z;
        if (dx*dx + dz*dz < 2 && r.starTimer <= 0) {
          r.spinTimer = 1.2;
          r.speed *= 0.3;
          scene.remove(ban.mesh);
          bananas.splice(b, 1);
        }
      }

      // Kart-to-kart bumping
      for (const other of racers) {
        if (other === r || other.finished) continue;
        const owp = other.getWorldPos();
        const oi = Math.floor(other.trackPos) % TRACK_LEN;
        const otan = trackTan[oi];
        const onx = -otan.z, onz = otan.x;
        const ox = owp.x + onx * other.lateralOffset;
        const oz = owp.z + onz * other.lateralOffset;
        const dx = worldX - ox, dz = worldZ - oz;
        if (dx*dx + dz*dz < 3) {
          // Push apart laterally
          r.lateralOffset += Math.sign(r.lateralOffset - other.lateralOffset) * 0.3;
          // Star beats other
          if (r.starTimer > 0 && other.starTimer <= 0) {
            other.spinTimer = 1;
            other.speed *= 0.2;
          }
        }
      }
    }
  }

  // ========== POSITION TRACKING ==========
  function updatePositions() {
    const sorted = [...racers].sort((a, b) => {
      if (a.finished && b.finished) return a.finishTime - b.finishTime;
      if (a.finished) return -1;
      if (b.finished) return 1;
      return b.totalProgress() - a.totalProgress();
    });
    sorted.forEach((r, i) => r.position = i + 1);
  }

  function ordinal(n) {
    const s = ['th','st','nd','rd'];
    const v = n % 100;
    return n + (s[(v-20)%10] || s[v] || s[0]);
  }

  // ========== UPDATE MESHES ==========
  function updateMeshes() {
    for (const r of racers) {
      const wp = r.getWorldPos();
      const heading = r.getHeading();
      const i = Math.floor(r.trackPos) % TRACK_LEN;
      const tan = trackTan[i];
      const nx = -tan.z, nz = tan.x;

      r.mesh.position.set(
        wp.x + nx * r.lateralOffset,
        0,
        wp.z + nz * r.lateralOffset
      );
      if (r.spinTimer > 0) {
        r.mesh.rotation.y = heading + r.spinTimer * 15;
      } else {
        r.mesh.rotation.y = heading;
      }

      // Star visual
      if (r.starTimer > 0) {
        r.mesh.children[0].material.emissive.setHex(0xffff00);
        r.mesh.children[0].material.emissiveIntensity = 0.6;
      } else {
        r.mesh.children[0].material.emissive.setHex(0x000000);
      }
    }

    // Rotate item boxes
    const t = performance.now() * 0.002;
    for (const box of itemBoxMeshes) {
      if (box.userData.alive) {
        box.rotation.y = t;
        box.position.y = 1 + Math.sin(t + box.position.x) * 0.3;
      }
    }

    // Banana aging
    for (let i = bananas.length - 1; i >= 0; i--) {
      bananas[i].life -= 0.016;
      if (bananas[i].life <= 0) {
        scene.remove(bananas[i].mesh);
        bananas.splice(i, 1);
      }
    }
  }

  // ========== CAMERA ==========
  function updateCamera() {
    const wp = player.getWorldPos();
    const heading = player.getHeading();
    const i = Math.floor(player.trackPos) % TRACK_LEN;
    const tan = trackTan[i];
    const nx = -tan.z, nz = tan.x;
    const px = wp.x + nx * player.lateralOffset;
    const pz = wp.z + nz * player.lateralOffset;

    // Behind-and-above camera
    const camDist = 12;
    const camH = 6;
    const targetX = px - Math.sin(heading) * camDist;
    const targetZ = pz - Math.cos(heading) * camDist;

    camera.position.lerp(new THREE.Vector3(targetX, camH, targetZ), 0.07);
    camera.lookAt(px, 0.5, pz);
  }

  // ========== MINIMAP ==========
  const minimapCanvas = document.getElementById('minimap');
  const mctx = minimapCanvas.getContext('2d');

  function drawMinimap() {
    const W = 180, H = 180;
    mctx.clearRect(0, 0, W, H);

    // Find bounding box
    let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity;
    for (const p of track) {
      if (p.x < minX) minX = p.x;
      if (p.x > maxX) maxX = p.x;
      if (p.z < minZ) minZ = p.z;
      if (p.z > maxZ) maxZ = p.z;
    }
    const pad = 20;
    const sx = (W - pad*2) / (maxX - minX);
    const sz = (H - pad*2) / (maxZ - minZ);
    const s = Math.min(sx, sz);
    const ox = pad + ((W - pad*2) - (maxX - minX)*s) / 2;
    const oz = pad + ((H - pad*2) - (maxZ - minZ)*s) / 2;

    const mapX = x => ox + (x - minX) * s;
    const mapZ = z => oz + (z - minZ) * s;

    // Draw track
    mctx.strokeStyle = '#444';
    mctx.lineWidth = 4;
    mctx.beginPath();
    for (let i = 0; i < TRACK_LEN; i++) {
      const fn = i === 0 ? 'moveTo' : 'lineTo';
      mctx[fn](mapX(track[i].x), mapZ(track[i].z));
    }
    mctx.closePath();
    mctx.stroke();

    // Draw racers
    for (const r of racers) {
      const wp = r.getWorldPos();
      const ti = Math.floor(r.trackPos) % TRACK_LEN;
      const tan = trackTan[ti];
      const nxi = -tan.z, nzi = tan.x;
      const rx = wp.x + nxi * r.lateralOffset;
      const rz = wp.z + nzi * r.lateralOffset;

      mctx.beginPath();
      mctx.arc(mapX(rx), mapZ(rz), r.isPlayer ? 5 : 3, 0, Math.PI * 2);
      mctx.fillStyle = '#' + KART_COLORS[r.idx].toString(16).padStart(6, '0');
      mctx.fill();
      if (r.isPlayer) {
        mctx.strokeStyle = '#fff';
        mctx.lineWidth = 2;
        mctx.stroke();
      }
    }
  }

  // ========== HUD ==========
  function updateHUD() {
    hudPos.textContent = ordinal(player.position);
    hudLap.textContent = `Lap ${Math.min(player.lap + 1, TOTAL_LAPS)} / ${TOTAL_LAPS}`;
    hudSpeed.textContent = Math.floor(player.speed * 500) + ' km/h';
    hudItem.textContent = player.item ? ITEM_EMOJI[player.item] : '';
  }

  // ========== COUNTDOWN ==========
  function doCountdown() {
    gameState = 'countdown';
    countdownEl.style.display = 'flex';
    let count = 3;
    countdownEl.textContent = count;
    const interval = setInterval(() => {
      count--;
      if (count > 0) {
        countdownEl.textContent = count;
      } else if (count === 0) {
        countdownEl.textContent = 'GO!';
        countdownEl.style.color = '#0f0';
      } else {
        clearInterval(interval);
        countdownEl.style.display = 'none';
        countdownEl.style.color = '#fff';
        gameState = 'racing';
      }
    }, 800);
  }

  // ========== FINISH ==========
  function checkFinished() {
    if (racers.every(r => r.finished)) {
      gameState = 'finished';
      showResults();
    }
    // Also end if player finishes
    if (player.finished && gameState === 'racing') {
      // Let AI finish quickly
      setTimeout(() => {
        racers.forEach(r => { if (!r.finished) { r.finished = true; r.finishTime = raceTime + Math.random()*3; }});
        gameState = 'finished';
        showResults();
      }, 2000);
    }
  }

  function showResults() {
    const sorted = [...racers].sort((a, b) => a.finishTime - b.finishTime);
    let html = '';
    sorted.forEach((r, i) => {
      const cls = r.isPlayer ? ' class="you"' : '';
      html += `<div${cls}>${ordinal(i+1)} — ${r.name} (${r.finishTime.toFixed(1)}s)</div>`;
    });
    resultsTable.innerHTML = html;
    resultsTitle.textContent = player.position <= 3 ? '\u{1F3C6} ' + ordinal(player.position) + ' PLACE!' : 'RACE COMPLETE';
    resultsEl.style.display = 'flex';
  }

  // ========== MAIN LOOP ==========
  let lastTime = 0;

  function loop(time) {
    requestAnimationFrame(loop);
    const dt = Math.min((time - lastTime) / 1000, 0.05);
    lastTime = time;

    if (gameState === 'racing') {
      raceTime += dt;
      updatePlayer(dt);
      for (let i = 1; i < racers.length; i++) updateAI(racers[i], dt);
      checkCollisions();
      updatePositions();
      checkFinished();
    }

    updateMeshes();
    updateCamera();
    updateHUD();
    drawMinimap();
    renderer.render(scene, camera);
  }

  // ========== START ==========
  function startRace() {
    overlay.style.display = 'none';
    resultsEl.style.display = 'none';
    raceTime = 0;
    // Reset bananas
    bananas.forEach(b => scene.remove(b.mesh));
    bananas.length = 0;
    // Reset item boxes
    itemBoxMeshes.forEach(b => { b.userData.alive = true; b.visible = true; });
    initRacers();
    doCountdown();
  }

  document.getElementById('startBtn').addEventListener('click', startRace);
  document.getElementById('restartBtn').addEventListener('click', startRace);

  // Initial state
  initRacers();
  document.getElementById('hud').style.display = 'none';
  requestAnimationFrame(loop);

  // Show HUD when game starts
  const origStart = startRace;
  const patchedStart = () => {
    document.getElementById('hud').style.display = 'flex';
    origStart();
  };
  document.getElementById('startBtn').onclick = patchedStart;
  document.getElementById('restartBtn').onclick = patchedStart;
})();
