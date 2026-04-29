export const keys = {forward:false,back:false,left:false,right:false,shoot:false,toggleCam:false};
window.addEventListener('keydown',e=>{
  switch(e.code){
    case 'ArrowUp':keys.forward=true;break;
    case 'ArrowDown':keys.back=true;break;
    case 'ArrowLeft':keys.left=true;break;
    case 'ArrowRight':keys.right=true;break;
    case 'Space':keys.shoot=true;break;
    case 'KeyC':keys.toggleCam=true;break;
  }
});
window.addEventListener('keyup',e=>{
  switch(e.code){
    case 'ArrowUp':keys.forward=false;break;
    case 'ArrowDown':keys.back=false;break;
    case 'ArrowLeft':keys.left=false;break;
    case 'ArrowRight':keys.right=false;break;
    case 'Space':keys.shoot=false;break;
    case 'KeyC':keys.toggleCam=false;break;
  }
});