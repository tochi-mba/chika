import * as THREE from 'three';
import {keys} from './controls.js';
import {Bullet} from './bullet.js';
export class Player {
  constructor(scene,camera){
    this.scene=scene;this.camera=camera;
    this.mesh=new THREE.Mesh(new THREE.BoxGeometry(1,2,1),new THREE.MeshStandardMaterial({color:0x00ff00}));
    this.mesh.position.y=1;
    scene.add(this.mesh);
    this.speed=0.1;this.bullets=[];this.fpView=true;this.canToggle=true;
  }
  update(){
    const dir=new THREE.Vector3();
    if(keys.forward) this.mesh.translateZ(-this.speed);
    if(keys.back) this.mesh.translateZ(this.speed);
    if(keys.left) this.mesh.rotation.y+=0.05;
    if(keys.right) this.mesh.rotation.y-=0.05;
    if(keys.toggleCam&&this.canToggle){this.fpView=!this.fpView;this.canToggle=false;setTimeout(()=>this.canToggle=true,300);}    
    if(keys.shoot){this.shoot();keys.shoot=false;}
    this.updateCamera();
    this.bullets.forEach(b=>b.update());
  }
  updateCamera(){
    if(this.fpView){
      this.camera.position.copy(this.mesh.position);
      this.camera.position.y+=1.5;
      this.camera.rotation.y=this.mesh.rotation.y;
    } else {
      const offset=new THREE.Vector3(0,3,8).applyAxisAngle(new THREE.Vector3(0,1,0),this.mesh.rotation.y);
      this.camera.position.copy(this.mesh.position.clone().add(offset));
      this.camera.lookAt(this.mesh.position);
    }
  }
  shoot(){
    const bullet=new Bullet(this.scene,this.mesh.position.clone(),this.mesh.rotation.y);
    this.bullets.push(bullet);
  }
}