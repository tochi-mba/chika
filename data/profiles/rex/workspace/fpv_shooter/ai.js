import * as THREE from 'three';
export class Bot {
  constructor(scene){
    this.scene=scene;
    this.mesh=new THREE.Mesh(new THREE.BoxGeometry(1,2,1),new THREE.MeshStandardMaterial({color:0xff0000}));
    this.mesh.position.set((Math.random()-0.5)*40,1,(Math.random()-0.5)*40);
    scene.add(this.mesh);
    this.speed=0.05;this.target=null;this.changeDir();this.switchTime=200+Math.random()*200;
  }
  changeDir(){this.dirAngle=Math.random()*Math.PI*2;}
  update(player){
    this.switchTime--;
    const dist=this.mesh.position.distanceTo(player.mesh.position);
    if(dist<15){this.mesh.lookAt(player.mesh.position);this.mesh.translateZ(-this.speed*2);} else {
      if(this.switchTime<0){this.changeDir();this.switchTime=200+Math.random()*200;}
      this.mesh.rotation.y=this.dirAngle;this.mesh.translateZ(-this.speed);
    }
  }
}