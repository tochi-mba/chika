import * as THREE from 'three';
import {Player} from './player.js';
import {Bot} from './ai.js';
let scene,camera,renderer,player,bots=[];
init();animate();
function init(){
  scene=new THREE.Scene();
  scene.background=new THREE.Color(0x202020);
  camera=new THREE.PerspectiveCamera(75,window.innerWidth/window.innerHeight,0.1,1000);\n  camera.position.set(0,2,10);\n  camera.lookAt(0,0,0);\n  scene.add(new THREE.GridHelper(100,100));\n  scene.add(new THREE.AxesHelper(5));
  renderer=new THREE.WebGLRenderer({antialias:true});
  renderer.setSize(window.innerWidth,window.innerHeight);
  document.body.appendChild(renderer.domElement);
  const light=new THREE.DirectionalLight(0xffffff,1);light.position.set(5,10,7);scene.add(light);
  scene.add(new THREE.AmbientLight(0x404040));
  const ground=new THREE.Mesh(new THREE.PlaneGeometry(100,100),new THREE.MeshStandardMaterial({color:0x555555}));
  ground.rotation.x=-Math.PI/2;scene.add(ground);
  player=new Player(scene,camera);
  for(let i=0;i<3;i++) bots.push(new Bot(scene));
  window.addEventListener('resize',()=>{
    camera.aspect=window.innerWidth/window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth,window.innerHeight);
  });
}
function animate(){
  requestAnimationFrame(animate);
  player.update();
  bots.forEach(b=>b.update(player));
  renderer.render(scene,camera);
}