import * as THREE from 'three';
export class Bullet{
  constructor(scene,pos,rotY){
    this.scene=scene;
    this.mesh=new THREE.Mesh(new THREE.SphereGeometry(0.1,8,8),new THREE.MeshBasicMaterial({color:0xffff00}));
    this.mesh.position.copy(pos);
    scene.add(this.mesh);
    this.dir=new THREE.Vector3(Math.sin(rotY),0,Math.cos(rotY)).multiplyScalar(-1);
    this.speed=0.5;this.life=100;
  }
  update(){this.mesh.position.add(this.dir.clone().multiplyScalar(this.speed));if(--this.life<=0){this.scene.remove(this.mesh);} }
}