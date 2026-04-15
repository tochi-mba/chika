const canvas = document.getElementById('gameCanvas');
const ctx = canvas.getContext('2d');
const startBtn = document.getElementById('startBtn');
const overlay = document.getElementById('overlay');
const box = 20;
let snake, direction, food, score, game, particles = [];
let running = false;

let particleColor = document.getElementById('particleColor').value;
let particleShape = document.getElementById('particleShape').value;
let particleStyle = document.getElementById('particleStyle').value;

document.getElementById('particleColor').addEventListener('input', e => particleColor = e.target.value);
document.getElementById('particleShape').addEventListener('change', e => particleShape = e.target.value);
document.getElementById('particleStyle').addEventListener('change', e => particleStyle = e.target.value);

startBtn.addEventListener('click', startGame);

document.addEventListener('keydown', directionEvent);

function startGame(){
  overlay.style.display = 'none';
  canvas.style.display = 'block';
  resetGame();
  running = true;
  game = setInterval(draw, 100);
}

function resetGame(){
  snake = [{x:9*box, y:9*box}];
  direction = 'RIGHT';
  food = {x: Math.floor(Math.random()*20)*box, y: Math.floor(Math.random()*20)*box};
  score = 0;
  particles = [];
}

function directionEvent(event){
  if(event.key === 'ArrowLeft' && direction !== 'RIGHT') direction = 'LEFT';
  else if(event.key === 'ArrowUp' && direction !== 'DOWN') direction = 'UP';
  else if(event.key === 'ArrowRight' && direction !== 'LEFT') direction = 'RIGHT';
  else if(event.key === 'ArrowDown' && direction !== 'UP') direction = 'DOWN';
}

function addParticles(x, y) {
  for(let i=0; i<5; i++) {
    particles.push({x:x, y:y, vx:(Math.random()-0.5)*2, vy:(Math.random()-0.5)*2, life:30});
  }
}

function drawParticles() {
  particles.forEach((p, i) => {
    p.life--;
    p.x += p.vx;
    p.y += p.vy;
    let alpha = p.life/30;
    ctx.globalAlpha = alpha;
    ctx.fillStyle = particleColor;
    if(particleShape==='circle'){
      ctx.beginPath();
      ctx.arc(p.x,p.y,2,0,Math.PI*2);
      ctx.fill();
    } else {
      ctx.fillRect(p.x,p.y,4,4);
    }
    ctx.globalAlpha = 1;
    if(p.life<=0) particles.splice(i,1);
  });
}

function draw(){
  ctx.fillStyle = '#111';
  ctx.fillRect(0,0,400,400);
  for(let i=0;i<snake.length;i++){
    ctx.fillStyle = i===0?'lime':'green';
    ctx.fillRect(snake[i].x, snake[i].y, box, box);
    if(i>0) addParticles(snake[i].x+box/2,snake[i].y+box/2);
  }
  drawParticles();
  ctx.fillStyle='red';
  ctx.fillRect(food.x,food.y,box,box);
  let snakeX=snake[0].x;
  let snakeY=snake[0].y;

  if(direction==='LEFT') snakeX-=box;
  if(direction==='UP') snakeY-=box;
  if(direction==='RIGHT') snakeX+=box;
  if(direction==='DOWN') snakeY+=box;

  if(snakeX===food.x&&snakeY===food.y){
    score++;
    food={x:Math.floor(Math.random()*20)*box,y:Math.floor(Math.random()*20)*box};
  } else snake.pop();

  const newHead={x:snakeX,y:snakeY};
  if(snakeX<0||snakeY<0||snakeX>=400||snakeY>=400||collision(newHead,snake)){
    clearInterval(game);
    running=false;
    showGameOver();
  }
  snake.unshift(newHead);
  ctx.fillStyle='white';
  ctx.font='20px Arial';
  ctx.fillText('Score: '+score,10,390);
}

function collision(head,array){
  for(let i=0;i<array.length;i++){
    if(head.x===array[i].x&&head.y===array[i].y)return true;
  }
  return false;
}

function showGameOver(){
  overlay.style.display='flex';
  canvas.style.display='none';
  overlay.querySelector('#overlay-content p').innerText='Game Over! Your score: '+score;
  startBtn.innerText='Play Again';
}