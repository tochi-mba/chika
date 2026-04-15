import * as THREE from 'https://cdn.jsdelivr.net/npm/three@0.159.0/build/three.module.js';

let scene, camera, renderer, player, bullets = [], enemies = [], score = 0, playerHealth = 100;

const clock = new THREE.Clock();

init();
animate();

function init() {
  scene = new THREE.Scene();

  camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
  camera.position.set(0, 1.6, 0);

  renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setSize(window.innerWidth, window.innerHeight);
  document.body.appendChild(renderer.domElement);

  const light = new THREE.HemisphereLight(0xffffff, 0x444444);
  light.position.set(0, 200, 0);
  scene.add(light);

  const floorGeometry = new THREE.PlaneGeometry(100, 100);
  const floorMaterial = new THREE.MeshPhongMaterial({ color: 0x555555 });
  const floor = new THREE.Mesh(floorGeometry, floorMaterial);
  floor.rotation.x = -Math.PI / 2;
  scene.add(floor);

  // Create player holder
  player = new THREE.Object3D();
  player.position.set(0, 1.6, 5);
  scene.add(player);

  // Add simple player body
  const playerBody = new THREE.Mesh(new THREE.CapsuleGeometry(0.5, 1), new THREE.MeshBasicMaterial({ color: 0x00ff00 }));
  playerBody.visible = false;
  player.add(playerBody);

  player.add(camera);

  // Spawn enemies
  for (let i = 0; i < 5; i++) spawnEnemy();

  // Mouse control
  document.body.requestPointerLock = document.body.requestPointerLock || document.body.mozRequestPointerLock;
  document.body.addEventListener('click', () => document.body.requestPointerLock());
  
  let move = { forward: 0, right: 0 };
  const speed = 10;

  document.addEventListener('keydown', (e) => {
    if (e.code === 'KeyW') move.forward = 1;
    if (e.code === 'KeyS') move.forward = -1;
    if (e.code === 'KeyA') move.right = -1;
    if (e.code === 'KeyD') move.right = 1;
    if (e.code === 'Space') shoot();
  });
  document.addEventListener('keyup', (e) => {
    if (['KeyW','KeyS'].includes(e.code)) move.forward = 0;
    if (['KeyA','KeyD'].includes(e.code)) move.right = 0;
  });

  document.addEventListener('mousemove', (e) => {
    if (document.pointerLockElement === document.body) {
      player.rotation.y -= e.movementX * 0.002;
      camera.rotation.x -= e.movementY * 0.002;
      camera.rotation.x = Math.max(-Math.PI/2, Math.min(Math.PI/2, camera.rotation.x));
    }
  });

  player.userData.move = move;
  player.userData.speed = speed;
  window.addEventListener('resize', onWindowResize);  
}

function spawnEnemy() {
  const enemy = new THREE.Mesh(
    new THREE.BoxGeometry(1, 2, 1),
    new THREE.MeshPhongMaterial({ color: 0xff0000 })
  );
  enemy.position.set((Math.random() - 0.5) * 50, 1, (Math.random() - 0.5) * 50);
  enemy.userData.health = 50;
  scene.add(enemy);
  enemies.push(enemy);
}

function onWindowResize() {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
}

function shoot() {
  const bullet = new THREE.Mesh(
    new THREE.SphereGeometry(0.1, 8, 8),
    new THREE.MeshBasicMaterial({ color: 0xffff00 })
  );
  const dir = new THREE.Vector3();
  camera.getWorldDirection(dir);
  bullet.position.copy(camera.position);
  bullet.userData.velocity = dir.multiplyScalar(50);
  bullets.push(bullet);
  scene.add(bullet);
}

function updateBullets(delta) {
  for (let i = bullets.length - 1; i >= 0; i--) {
    const b = bullets[i];
    b.position.addScaledVector(b.userData.velocity, delta);

    enemies.forEach(enemy => {
      if (b.position.distanceTo(enemy.position) < 1) {
        enemy.userData.health -= 25;
        scene.remove(b);
        bullets.splice(i, 1);
        if (enemy.userData.health <= 0) {
          scene.remove(enemy);
          enemies.splice(enemies.indexOf(enemy), 1);
          score++;
          document.getElementById('score').innerText = `Score: ${score}`;
          spawnEnemy();
        }
      }
    });
  }
}

function updateEnemies(delta) {
  enemies.forEach(enemy => {
    const dir = new THREE.Vector3().subVectors(player.position, enemy.position);
    const dist = dir.length();
    dir.normalize();

    if (dist > 3) {
      enemy.position.addScaledVector(dir, delta * 3);
    } else {
      playerHealth -= delta * 5; // simple attack
      if (playerHealth <= 0) {
        document.getElementById('health').innerText = 'Health: 0 - GAME OVER';
      } else {
        document.getElementById('health').innerText = `Health: ${Math.round(playerHealth)}`;
      }
    }
  });
}

function updatePlayer(delta) {
  const move = player.userData.move;
  const forward = new THREE.Vector3();
  player.getWorldDirection(forward);
  forward.y = 0;
  forward.normalize();

  const right = new THREE.Vector3().crossVectors(new THREE.Vector3(0,1,0), forward);

  player.position.addScaledVector(forward, move.forward * delta * player.userData.speed);
  player.position.addScaledVector(right, move.right * delta * player.userData.speed);
}

function animate() {
  requestAnimationFrame(animate);
  const delta = clock.getDelta();
  updatePlayer(delta);
  updateBullets(delta);
  updateEnemies(delta);
  renderer.render(scene, camera);
}