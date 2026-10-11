// A Crocetta-inspired daytime streetscape, deliberately illustrative rather than a site survey.
// Only visual scenery lives here. Crosswalk geometry and all operational layers stay in Twin.
import * as THREE from "three";
import { material, mesh, bevelBox, link, batchScenery } from "./visual-geometry.js";

const PLASTER = ['#d9c8a9', '#e3d7bc', '#bfae94', '#d1b69c', '#d7cdbb', '#c1b39b'];
const STONE = material(0xd8d3bf), IRON = material(0x43534b, {metalness:.35,roughness:.65});
const BARK = material(0x74654c);
const LEAVES = [0x536f40,0x567243,0x5c7747,0x4d6a3e].map(c=>material(c,{roughness:.98}));
const WOOD = material(0x94744f), SLATE = material(0x777a70);
const JOINT = material(0x9c9e90), TREE_BASE = material(0x7e8272), PLANTER = material(0x9e7860);

function canvasTexture(width, height, draw) {
  const canvas=document.createElement('canvas');canvas.width=width;canvas.height=height;
  draw(canvas.getContext('2d'),width,height);
  const texture=new THREE.CanvasTexture(canvas);
  texture.colorSpace=THREE.SRGBColorSpace;texture.anisotropy=4;
  return texture;
}

function noise(seed) {
  let value=seed>>>0;
  return ()=>{value=(Math.imul(value,1664525)+1013904223)>>>0;return value/4294967296;};
}

export function daylightEnvironment(renderer) {
  const sky=canvasTexture(512,256,(g,w,h)=>{
    const gradient=g.createLinearGradient(0,0,0,h);
    gradient.addColorStop(0,'#b5d0dc');gradient.addColorStop(.48,'#e5e9df');
    gradient.addColorStop(.53,'#bec1ad');gradient.addColorStop(1,'#858b78');
    g.fillStyle=gradient;g.fillRect(0,0,w,h);
    const glow=g.createRadialGradient(150,72,2,150,72,80);
    glow.addColorStop(0,'rgba(255,248,225,.95)');glow.addColorStop(1,'rgba(255,248,225,0)');
    g.fillStyle=glow;g.fillRect(0,0,w,h);
  });
  sky.mapping=THREE.EquirectangularReflectionMapping;
  const generator=new THREE.PMREMGenerator(renderer);
  const environment=generator.fromEquirectangular(sky).texture;
  generator.dispose();sky.dispose();
  return environment;
}

export function streetSurfaces() {
  const asphalt=canvasTexture(256,256,(g,w,h)=>{
    g.fillStyle='#737975';g.fillRect(0,0,w,h);
    const rnd=noise(43);
    for(let i=0;i<18000;i++) {
      const v=Math.floor(80+rnd()*65);g.fillStyle=`rgba(${v},${v+3},${v},.25)`;
      g.fillRect(rnd()*w,rnd()*h,1+rnd(),1+rnd());
    }
  });
  asphalt.wrapS=asphalt.wrapT=THREE.RepeatWrapping;
  asphalt.repeat.set(30,1.33);
  const paving=canvasTexture(256,256,(g,w,h)=>{
    const rnd=noise(97);g.fillStyle='#aaa89a';g.fillRect(0,0,w,h);
    for(let y=0;y<h;y+=64) for(let x=0;x<w;x+=64) {
      const v=188+Math.floor(rnd()*12);
      g.fillStyle=`rgb(${v+6},${v+5},${v-4})`;g.fillRect(x+1,y+1,62,62);
      g.strokeStyle='rgba(245,241,223,.4)';g.strokeRect(x+2,y+2,60,60);
    }
    for(let i=0;i<3000;i++) {g.fillStyle=rnd()>.5?'rgba(255,255,240,.07)':'rgba(66,60,48,.06)';g.fillRect(rnd()*w,rnd()*h,1,1);}
  });
  paving.wrapS=paving.wrapT=THREE.RepeatWrapping;
  return {asphalt,paving};
}

function facadeTexture(seed, bays, floors) {
  return canvasTexture(bays*128,(floors+1)*160,(g,w,h)=>{
    const rnd=noise(seed);
    g.fillStyle=PLASTER[seed%PLASTER.length];g.fillRect(0,0,w,h);
    // Fine plaster grain. All generation is deterministic and independent of simulator randomness.
    for(let i=0;i<9000;i++) {g.fillStyle=rnd()>.5?'rgba(255,250,224,.08)':'rgba(81,65,46,.045)';g.fillRect(rnd()*w,rnd()*h,1,1);}
    g.fillStyle='#9d9b8b';g.fillRect(0,h-157,w,157);
    for(let y=h-153;y<h;y+=24) {g.strokeStyle='rgba(61,62,53,.20)';g.beginPath();g.moveTo(0,y);g.lineTo(w,y);g.stroke();}
    const glass=g.createLinearGradient(0,0,70,140);glass.addColorStop(0,'#8caaa9');glass.addColorStop(.5,'#526e70');glass.addColorStop(1,'#334b4c');
    for(let floor=0;floor<floors;floor++) {
      const y=23+floor*160;
      for(let bay=0;bay<bays;bay++) {
        const x=bay*128+42;
        g.fillStyle='rgba(77,60,43,.18)';g.fillRect(x-12,y-7,66,119);
        g.fillStyle='#e9dfc7';g.fillRect(x-9,y-10,60,116);
        g.fillStyle=glass;g.fillRect(x,y,42,94);
        g.fillStyle='rgba(205,225,214,.3)';g.fillRect(x+3,y+3,15,37);
        g.fillStyle='#bcbba8';g.fillRect(x+20,y,3,94);g.fillRect(x,y+42,42,3);
        // Muted green shutters, with narrow horizontal louvres.
        for(const sx of [x-24,x+48]) {
          g.fillStyle=seed%2?'#546b58':'#647767';g.fillRect(sx,y,17,96);
          g.fillStyle='rgba(24,39,27,.26)';for(let sy=y+5;sy<y+94;sy+=6) g.fillRect(sx+2,sy,13,2);
        }
        g.fillStyle='#e6dcc5';g.fillRect(x-13,y+99,69,7);
        if(floor===0) {g.fillRect(x-15,y-15,71,5);g.fillRect(x+1,y-21,38,6);}
      }
      g.fillStyle='rgba(244,234,208,.70)';g.fillRect(0,y+131,w,3);
      g.fillStyle='rgba(103,84,61,.12)';g.fillRect(0,y+135,w,3);
    }
    for(let bay=0;bay<bays;bay++) {
      const x=bay*128+32,y=h-127;
      g.fillStyle='#ddcfb4';g.fillRect(x-7,y-7,78,125);
      g.fillStyle=bay===Math.floor(bays/2)?'#465448':'#4f6666';g.fillRect(x,y,64,116);
      g.fillStyle='#b8b1a0';g.fillRect(x+30,y,4,116);
      g.fillStyle='rgba(183,211,204,.17)';g.fillRect(x+5,y+6,23,65);
    }
  });
}

function roofGeometry(width, depth, height) {
  const w=width/2,d=depth/2;
  const vertices=[-w,0,d,w,0,d,-w,height,0,w,height,0,-w,0,-d,w,0,-d];
  const geometry=new THREE.BufferGeometry();
  geometry.setAttribute('position',new THREE.Float32BufferAttribute(vertices,3));
  geometry.setIndex([0,1,2,1,3,2,2,3,4,3,5,4,0,2,4,1,5,3]);
  geometry.computeVertexNormals();return geometry;
}

function building(parent,x,front,width,seed) {
  const g=new THREE.Group();g.position.set(x,0,front-6);parent.add(g);
  const floors=3+seed%3,bays=Math.max(3,Math.round(width/3.1));
  const height=(floors+1)*3.1,depth=12;
  const wall=material(new THREE.Color(PLASTER[seed%PLASTER.length]));
  const facade=material(0xffffff,{map:facadeTexture(seed,bays,floors),roughness:.95});
  // Six separate faces allow the whole streetscape to be merged by material later.
  mesh(g,new THREE.PlaneGeometry(width,height),facade,0,height/2,depth/2+.005,false);
  const back=mesh(g,new THREE.PlaneGeometry(width,height),wall,0,height/2,-depth/2,false);back.rotation.y=Math.PI;
  for(const side of [-1,1]) {
    const flank=mesh(g,new THREE.PlaneGeometry(depth,height),wall,side*width/2,height/2,0,false);flank.rotation.y=side*Math.PI/2;
  }
  const roof=mesh(g,roofGeometry(width+.55,depth+.55,1.35),SLATE,0,height,0,false);
  roof.receiveShadow=false;
  // Cornices, stone plinth, floor bands and shallow pilasters.
  for(const y of [.40,3.05,height-.30,height+.02]) mesh(g,new THREE.BoxGeometry(width+.32,y===height+.02?.28:.12,depth+.30),STONE,0,y,0,false);
  for(const side of [-1,1]) mesh(g,new THREE.BoxGeometry(.28,height-.8,.13),STONE,side*(width/2-.20),height/2,depth/2+.075,false);
  for(let floor=1;floor<=floors;floor++) {
    const y=floor*3.1;
    if(floor<floors) mesh(g,new THREE.BoxGeometry(width,.07,.16),STONE,0,y+.12,depth/2+.08,false);
    for(let bay=0;bay<bays;bay++) {
      const bx=-width/2+(bay+.5)*width/bays;
      mesh(g,new THREE.BoxGeometry(1.30,.09,.24),STONE,bx,y+.18,depth/2+.12,false);
      // Selected balconies give the facade actual depth without a dense lattice of geometry.
      if((bay+seed)%2!==0||floor===floors) continue;
      mesh(g,new THREE.BoxGeometry(1.92,.14,.70),STONE,bx,y+.16,depth/2+.35,false);
      for(const by of [y+.37,y+1.04]) mesh(g,new THREE.BoxGeometry(1.88,.035,.035),IRON,bx,by,depth/2+.68,false);
      for(let i=0;i<9;i++) mesh(g,new THREE.BoxGeometry(.025,.69,.025),IRON,bx-.86+i*.215,y+.70,depth/2+.68,false);
      for(const s of [-1,1]) {
        mesh(g,new THREE.BoxGeometry(.025,.70,.025),IRON,bx+s*.90,y+.70,depth/2+.04,false);
        mesh(g,new THREE.BoxGeometry(.025,.035,.66),IRON,bx+s*.90,y+1.04,depth/2+.35,false);
      }
      if((seed+floor+bay)%3===0) {
        mesh(g,bevelBox(.75,.22,.23,.035),PLANTER,bx,y+.47,depth/2+.48,false);
        const shrub=mesh(g,new THREE.SphereGeometry(.23,10,8),LEAVES[seed%4],bx,y+.66,depth/2+.48,false);shrub.scale.set(1.6,.55,.50);
      }
    }
  }
  for(const cx of [-width*.26,width*.27]) mesh(g,new THREE.BoxGeometry(.60,1.15,.70),wall,cx,height+.65,-1.8,false);
  // Canvas lettering is decoration; it is not a live data label.
  if(Math.abs(x)<25) {
    const sign=canvasTexture(256,64,(ctx,w,h)=>{
      ctx.fillStyle='#e8e1cd';ctx.fillRect(0,0,w,h);ctx.strokeStyle='#758074';ctx.lineWidth=5;ctx.strokeRect(5,5,w-10,h-10);
      ctx.fillStyle='#536451';ctx.font='600 25px Georgia';ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(seed%2?'CAFFÈ':'BOTTEGA',w/2,h/2);
    });
    mesh(g,new THREE.PlaneGeometry(2.15,.54),material(0xffffff,{map:sign}),-width*.25,2.55,depth/2+.025,false);
    const canopy=mesh(g,new THREE.BoxGeometry(2.6,.065,.85),material(seed%2?0x6b7c63:0xb29773),-width*.25,2.3,depth/2+.40,false);canopy.rotation.x=.18;
  }
}

function tree(parent,x,z,seed) {
  const g=new THREE.Group();g.position.set(x,0,z);parent.add(g);
  const height=3.2+(seed%3)*.25,shadow=Math.abs(x)<35;
  link(g,[0,.15,0],[.06,height,0],.16,BARK,shadow);
  for(let i=0;i<4;i++) {
    const angle=i*Math.PI/2+seed*.7;
    link(g,[0,height*.6,0],[Math.cos(angle)*.85,height+.65,Math.sin(angle)*.85],.075,BARK,shadow);
  }
  const crown=new THREE.SphereGeometry(1,12,10);
  const vertices=crown.getAttribute('position');
  for(let i=0;i<vertices.count;i++) {
    const x=vertices.getX(i),y=vertices.getY(i),z=vertices.getZ(i);
    const ripple=1+.08*Math.sin(x*10+y*12)+.06*Math.cos(z*13-y*11);
    vertices.setXYZ(i,x*ripple,y*ripple,z*ripple);
  }
  crown.computeVertexNormals();
  // Overlapping smooth leaf masses replace the single twenty-sided polyhedron.
  const rnd=noise(seed+100);
  for(let i=0;i<9;i++) {
    const angle=i*2.39996,rad=i===0?0:.65+rnd()*.42;
    const leaf=mesh(g,crown,LEAVES[(seed+i)%4],Math.cos(angle)*rad,height+.80+rnd()*.65,Math.sin(angle)*rad,shadow);
    leaf.scale.set(1.00+rnd()*.35,1.05+rnd()*.55,1.05+rnd()*.25);
  }
  for(let i=0;i<16;i++) {
    const angle=i*2.39996,rad=1.25+rnd()*.25;
    const leaf=mesh(g,crown,LEAVES[(seed+i+1)%4],Math.cos(angle)*rad,height+.45+rnd()*1.5,Math.sin(angle)*rad,shadow);
    leaf.scale.set(.48+rnd()*.28,.52+rnd()*.28,.48+rnd()*.28);
  }
  mesh(g,new THREE.BoxGeometry(1.9,.06,1.9),TREE_BASE,0,.17,0,false);
  const grate=mesh(g,new THREE.RingGeometry(.26,.80,24),IRON,0,.205,0,false);grate.rotation.x=-Math.PI/2;
}

function lamp(parent,x,z) {
  const g=new THREE.Group();g.position.set(x,0,z);parent.add(g);
  mesh(g,new THREE.CylinderGeometry(.12,.20,.42,12),IRON,0,.34,0,false);
  mesh(g,new THREE.CylinderGeometry(.045,.085,4.55,12),IRON,0,2.65,0,false);
  link(g,[0,4.88,0],[.48,5.02,0],.04,IRON,false);
  mesh(g,bevelBox(.62,.12,.25,.04),IRON,.56,4.99,0,false);
  mesh(g,new THREE.PlaneGeometry(.43,.14),material(0xe6e4cb),.56,4.925,0,false).rotation.x=Math.PI/2;
}

function bench(parent,x,z,side) {
  const g=new THREE.Group();g.position.set(x,0,z);g.rotation.y=side===1?Math.PI:0;parent.add(g);
  for(const bx of [-.70,.70]) {
    mesh(g,new THREE.BoxGeometry(.06,.48,.50),IRON,bx,.39,0,false);
    mesh(g,new THREE.BoxGeometry(.06,.65,.05),IRON,bx,.67,-.22,false);
  }
  for(let i=0;i<4;i++) mesh(g,new THREE.BoxGeometry(1.9,.055,.09),WOOD,0,.61,-.18+i*.12,false);
  for(let i=0;i<3;i++) mesh(g,new THREE.BoxGeometry(1.9,.09,.05),WOOD,0,.82+i*.12,-.25,false);
}

export function buildStreetscape(sceneCfg, walkWidth, far) {
  const city=new THREE.Group(),L=sceneCfg.crosswalk.length,W=sceneCfg.crosswalk.width;
  const front=-(L/2+walkWidth+1.2);
  let x=-far,seed=1;
  // Far side remains a cutaway, so the crossing is visible from the established default camera.
  while(x<far) {
    const width=12+(seed*7)%6;
    building(city,x+width/2,front,width-.25,seed);
    x+=width;seed++;
  }
  for(const s of [-1,1]) {
    let i=0;
    for(let tx=-far+6;tx<far;tx+=13) {
      if(Math.abs(tx)<W/2+5) continue;
      tree(city,tx,s*(L/2+walkWidth-.95),++i+(s===1?10:0));
    }
    for(let lx=-far+10;lx<far;lx+=24) {
      if(Math.abs(lx)<W/2+4) continue;
      lamp(city,lx,s*(L/2+1.0));
    }
    for(const bx of [-16,16]) bench(city,bx,s*(L/2+walkWidth-1),s);
    for(const bx of [-7,-5,5,7]) {
      mesh(city,new THREE.CylinderGeometry(.075,.10,.72,10),IRON,bx,.51,s*(L/2+.55),false);
      mesh(city,new THREE.SphereGeometry(.082,10,8),IRON,bx,.88,s*(L/2+.55),false);
    }
    // Granite curb joints and a drain beside (never across) the crossing.
    for(let cx=-far;cx<far;cx+=1.25) mesh(city,new THREE.BoxGeometry(.018,.012,.19),JOINT,cx,.176,s*(L/2+.10),false);
    const grate=mesh(city,new THREE.BoxGeometry(.62,.01,.26),IRON,W/2+2.4,.016,s*(L/2-.20),false);
    for(let i=0;i<6;i++) mesh(city,new THREE.BoxGeometry(.025,.012,.21),STONE,grate.position.x-.25+i*.1,.024,grate.position.z,false);
  }
  return batchScenery(city);
}
