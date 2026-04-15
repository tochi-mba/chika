const canvas = document.getElementById('gameCanvas');
const ctx = canvas.getContext('2d');
const tileSize = 16;
const map = [
  [1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],
  [1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1],
  [1,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,1],
  [1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1],
  [1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1]
];

let pacman = { x: tileSize, y: tileSize, dx: tileSize, dy: 0 };

function drawMap() {
  for (let row = 0; row < map.length; row++) {
    for (let col = 0; col < map[row].length; col++) {
      if (map[row][col] === 1) {
        ctx.fillStyle = 'blue';
        ctx.fillRect(col * tileSize, row * tileSize, tileSize, tileSize);
      } else {
        ctx.fillStyle = 'black';
        ctx.fillRect(col * tileSize, row * tileSize, tileSize, tileSize);
        ctx.beginPath();
        ctx.arc(col * tileSize + tileSize / 2, row * tileSize + tileSize / 2, 2, 0, Math.PI * 2);
        ctx.fillStyle = 'white';
        ctx.fill();
      }
    }
  }
}

function drawPacman() {
  ctx.beginPath();
  ctx.arc(pacman.x + tileSize / 2, pacman.y + tileSize / 2, tileSize / 2, 0.25 * Math.PI, 1.75 * Math.PI);
  ctx.lineTo(pacman.x + tileSize / 2, pacman.y + tileSize / 2);
  ctx.fillStyle = 'yellow';
  ctx.fill();
}

function movePacman() {
  let newX = pacman.x + pacman.dx;
  let newY = pacman.y + pacman.dy;
  const col = Math.floor(newX / tileSize);
  const row = Math.floor(newY / tileSize);
  if (map[row][col] !== 1) {
    pacman.x = newX;
    pacman.y = newY;
  }
}

function update() {
  movePacman();
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  drawMap();
  drawPacman();
  requestAnimationFrame(update);
}

window.addEventListener('keydown', (e) => {
  switch(e.key) {
    case 'ArrowUp': pacman.dx = 0; pacman.dy = -tileSize; break;
    case 'ArrowDown': pacman.dx = 0; pacman.dy = tileSize; break;
    case 'ArrowLeft': pacman.dx = -tileSize; pacman.dy = 0; break;
    case 'ArrowRight': pacman.dx = tileSize; pacman.dy = 0; break;
  }
});

drawMap();
drawPacman();
requestAnimationFrame(update);