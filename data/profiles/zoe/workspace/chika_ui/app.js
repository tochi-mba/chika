// Initialize THREE.js scene
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
const renderer = new THREE.WebGLRenderer({ canvas: document.getElementById('sphereCanvas'), alpha: true });
renderer.setSize(window.innerWidth * 0.66, window.innerHeight);

const geometry = new THREE.SphereGeometry(2, 64, 64);
const material = new THREE.MeshPhongMaterial({ color: 0x00ffff, shininess: 100 });
const sphere = new THREE.Mesh(geometry, material);
scene.add(sphere);

// Lighting
const light = new THREE.PointLight(0xffffff, 1);
light.position.set(5, 5, 5);
scene.add(light);
const ambientLight = new THREE.AmbientLight(0x404040);
scene.add(ambientLight);

camera.position.z = 5;
let direction = 1;

// Animate sphere movement
function animate() {
  requestAnimationFrame(animate);
  sphere.rotation.x += 0.01;
  sphere.rotation.y += 0.01;
  sphere.position.x += 0.02 * direction;
  if (Math.abs(sphere.position.x) > 2) direction *= -1;
  renderer.render(scene, camera);
}
animate();

// Chat logic—connect to Chika backend
const messages = document.getElementById('messages');
const input = document.getElementById('chat-input');

async function sendMessageToChika(text) {
  const msg = document.createElement('div');
  msg.textContent = 'You: ' + text;
  messages.appendChild(msg);

  const response = await fetch('http://localhost:8000/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: text })
  });
  const data = await response.json();

  const reply = document.createElement('div');
  reply.textContent = 'Chika: ' + data.reply;
  messages.appendChild(reply);
}

input.addEventListener('keypress', (e) => {
  if (e.key === 'Enter' && input.value.trim() !== '') {
    sendMessageToChika(input.value.trim());
    input.value = '';
  }
});