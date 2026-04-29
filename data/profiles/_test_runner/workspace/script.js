import * as THREE from './three.module.min.js';
import { OrbitControls } from './OrbitControls.min.js';

let scene, camera, renderer, particles, uniforms;

init();
animate();

function init() {
  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
  camera.position.z = 70;

  renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.setClearColor(0x000000, 1);
  document.body.appendChild(renderer.domElement);

  const geometry = new THREE.BufferGeometry();
  const particleCount = 3000;
  const positions = new Float32Array(particleCount * 3);
  const colors = new Float32Array(particleCount * 3);

  for (let i = 0; i < particleCount; i++) {
    const radius = Math.random() * 50;
    const angle = Math.random() * Math.PI * 2;
    const y = (Math.random() - 0.5) * 40;
    positions[i * 3] = Math.cos(angle) * radius;
    positions[i * 3 + 1] = y;
    positions[i * 3 + 2] = Math.sin(angle) * radius;

    const color = new THREE.Color(`hsl(${Math.random() * 360}, 100%, 60%)`);
    colors[i * 3] = color.r;
    colors[i * 3 + 1] = color.g;
    colors[i * 3 + 2] = color.b;
  }

  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));

  const material = new THREE.PointsMaterial({ size: 0.8, vertexColors: true, transparent: true, opacity: 0.8, blending: THREE.AdditiveBlending });
  particles = new THREE.Points(geometry, material);
  scene.add(particles);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.05;

  window.addEventListener('resize', () => {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
  });
}

function animate() {
  requestAnimationFrame(animate);
  const positions = particles.geometry.attributes.position.array;
  for (let i = 0; i < positions.length; i += 3) {
    positions[i + 1] += Math.sin(Date.now() * 0.0003 + i) * 0.01;
    positions[i] += Math.cos(Date.now() * 0.0002 + i) * 0.01;
    positions[i + 2] += Math.sin(Date.now() * 0.0004 + i) * 0.01;
  }
  particles.geometry.attributes.position.needsUpdate = true;
  particles.rotation.y += 0.001;
  renderer.render(scene, camera);
}