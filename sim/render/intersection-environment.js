import * as THREE from "three";
import { addBuildings } from "./context.js";

const vector = (x,y,z=0) => new THREE.Vector3(x,z,-y);
const forwards = {N:[0,-1],E:[-1,0],S:[0,1],W:[1,0]};

export async function buildIntersection(scene, geometry, seed, conditions) {
  const loader = new THREE.TextureLoader();
  const [map,normalMap,roughnessMap] = await Promise.all(
    ["asphalt.jpg","asphalt-normal.jpg","asphalt-rough.jpg"].map(name=>loader.loadAsync(`./assets/${name}`)));
  map.colorSpace = THREE.SRGBColorSpace;
  for(const texture of [map,normalMap,roughnessMap]) {
    texture.wrapS=texture.wrapT=THREE.RepeatWrapping;
    texture.repeat.set(geometry.approach/2,geometry.half_road/2);
    texture.anisotropy=8;
  }
  const wet=conditions.weather==="rain";
  const asphalt=new THREE.MeshPhysicalMaterial({map,normalMap,roughnessMap:wet?null:roughnessMap,
    roughness:wet?.24:.95,clearcoat:wet?.55:0,color:0xbfc3bd});
  const concrete=new THREE.MeshStandardMaterial({color:0xb9b9b1,roughness:.94});
  const paint=new THREE.MeshStandardMaterial({color:0xe6e3d9,roughness:wet?.4:.85});
  const metal=new THREE.MeshStandardMaterial({color:0x535b5d,metalness:.75,roughness:.45});
  const dark=new THREE.MeshStandardMaterial({color:0x182522,roughness:.7});
  const h=geometry.half_road,A=geometry.approach,lane=geometry.lane_width;
  const lamps=[];
  function box(w,d,height,x,y,z,material,parent=scene) {
    const mesh=new THREE.Mesh(new THREE.BoxGeometry(w,height,d),material);
    mesh.position.copy(vector(x,y,z+height/2));mesh.castShadow=mesh.receiveShadow=true;parent.add(mesh);return mesh;
  }
  box(A*2+40,A*2+40,.08,0,0,-.1,concrete);
  box(A*2,h*2,.02,0,0,-.015,asphalt);
  box(h*2,A*2,.021,0,0,-.01,asphalt);
  for(const sx of [-1,1])for(const sy of [-1,1]) {
    box(A-h,A-h,.16,sx*(A+h)/2,sy*(A+h)/2,0,concrete);
    box(A-h,.22,.19,sx*(A+h)/2,sy*(h+.11),0,concrete);
    box(.22,A-h,.19,sx*(h+.11),sy*(A+h)/2,0,concrete);
  }
  function signal(id,x,y,z,rotation,ped=false) {
    const group=new THREE.Group();group.position.copy(vector(x,y,z));group.rotation.y=rotation;scene.add(group);
    box(.6,.35,ped?.9:1.6,0,0,ped?-.45:-.8,dark,group);
    const names=ped?["red","green"]:["red","yellow","green"];
    for(let i=0;i<names.length;i++) {
      const mat=new THREE.MeshStandardMaterial({color:0x17221c,emissive:0,roughness:.35});
      const bulb=new THREE.Mesh(new THREE.SphereGeometry(.16,12,8),mat);bulb.scale.z=.5;
      bulb.position.set(0,(names.length-1)*.26-i*.52,.20);group.add(bulb);
      lamps.push({id,name:names[i],material:mat});
    }
  }
  for(const [arm,[fx,fy]] of Object.entries(forwards)) {
    const rx=fy,ry=-fx,at=(radius,offset)=>[-fx*radius+rx*offset,-fy*radius+ry*offset];
    for(let radius=19;radius<A-3;radius+=6)for(const offset of [-lane,0,lane]) {
      const [x,y]=at(radius,offset);box(Math.abs(fx)?3:.10,Math.abs(fy)?3:.10,.005,x,y,.025,paint);
    }
    for(let offset=-h+.35;offset<h;offset+=.95) {
      const [x,y]=at(geometry.crossing_radius,offset);
      box(Math.abs(rx)>.5?.48:geometry.crosswalk_width,Math.abs(ry)>.5?.48:geometry.crosswalk_width,.005,x,y,.03,paint);
    }
    const [sx,sy]=at(geometry.stop_radius,h/2);
    box(Math.abs(rx)>.5?h:.24,Math.abs(ry)>.5?h:.24,.005,sx,sy,.03,paint);
    const [px,py]=at(geometry.stop_radius+1,h+1);
    box(.14,.14,5,px,py,0,metal);
    const [cx,cy]=at(geometry.stop_radius+1,h/2);
    box(Math.abs(rx)>.5?h+2:.14,Math.abs(ry)>.5?h+2:.14,.14,cx,cy,4.6,metal);
    for(const [turn,offset] of [["left",lane*.5],["straight",lane*1.5]]) {
      const [x,y]=at(geometry.stop_radius+1,offset);
      signal(`${arm}_${turn}`,x,y,4.0,Math.atan2(-fx,-fy));
    }
    for(const side of [-1,1]) {
      const [x,y]=at(geometry.crossing_radius+1,side*(h+1));
      box(.09,.09,2.5,x,y,0,metal);signal(`ped_${arm}`,x,y,2.1,Math.atan2(rx*side,ry*side),true);
      const light=new THREE.PointLight(0xffecd1,conditions.time_of_day==="night"?85:0,26,2);
      light.position.copy(vector(x,y,5));scene.add(light);
    }
  }
  const context=addBuildings(scene,{approach:A,crosswalk:{length:28},curb_depth:3,sidewalk_width:4,intersection:true},seed,conditions);
  const colors={red:0xe02615,yellow:0xffb620,green:0x27cf5c};
  scene.userData.updateIntersectionSignals = signalState => {
    if(!signalState)return;
    for(const lamp of lamps) {
      let state=lamp.id.startsWith("ped_")?signalState.pedestrians[lamp.id.slice(4)]:signalState.vehicles[lamp.id];
      if(state==="flash")state=Math.floor(signalState.elapsed_s*2)%2===0?"green":"off";
      const on=state===lamp.name;
      lamp.material.color.setHex(on?colors[lamp.name]:0x17221c);
      lamp.material.emissive.setHex(on?colors[lamp.name]:0);lamp.material.emissiveIntensity=on?1.8:0;
    }
  };
  return {...context,mode:"four-arm intersection",crosswalks:4,signal_bulbs:lamps.length};
}
