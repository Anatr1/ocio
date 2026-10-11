const $=id=>document.getElementById(id);
const config=await (await fetch('/api/config')).json();
if(config.render_mode==='photoreal') {
  $('camera-card').hidden=false;
  const vision=config.observation_mode==='vision';
  if(vision){
    $('camera-select').querySelector('[value="overview"]').remove();
    document.querySelector('.legend-note').textContent='Reconstructed NN tracks';
    document.querySelector('.scene-heading p').textContent='Four camera views → NN perception → reconstructed digital twin.';
    document.querySelector('.comparison-card .card-label').textContent='GROUND-TRUTH POLICY BENCHMARK';
    document.querySelector('.comparison-card>p').textContent='Compare the policies with perfect observations as a separate reference benchmark.';
    document.querySelector('.approach-table').nextElementSibling.textContent='Observed passages and stationary waits. Through/right intent is estimated only after an exit is seen.';
    document.querySelector('.phase-card .subtle').textContent='Signals use perceived demand and occupancy. Missing detections can affect clearance.';
    document.querySelector('.pedestrian-card .subtle').textContent='Stage a slow walker and inspect perceived crossing clearance.';
  }else $('camera-explanation').textContent='RGB preview; enable --intersection-detector real for a perception-driven twin.';
  let pending=false,lastFrame='';
  $('camera-select').onchange=async event=>{
    lastFrame='';
    const response=await fetch('/api/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'camera',camera:event.target.value})});
    if(!response.ok)$('camera-status').textContent=(await response.json()).error;
  };
  $('camera-boxes').onchange=()=>lastFrame='';
  $('camera-visible').onchange=()=>{ $('pixel-view').hidden=!$('camera-visible').checked;lastFrame=''; };
  async function refresh(){
    if(pending)return;pending=true;
    try{
      const state=await(await fetch('/api/state')).json(),camera=state.camera;
      if(!camera)return;
      $('camera-select').value=camera.camera;
      $('camera-status').textContent=`${camera.detector==='real'?'Real YOLO':'RGB preview'} · ${camera.camera} · ${camera.frame_t.toFixed(1)} s · ${camera.predictions.length} detections${vision?` · ${camera.fused_tracks} fused tracks · 4 cameras`:''}`;
      const signature=`${camera.generation}:${camera.frames}:${camera.camera}:${$('camera-boxes').checked}`;
      if($('camera-visible').checked&&signature!==lastFrame){lastFrame=signature;$('camera-image').src=`/api/camera${$('camera-boxes').checked?'':'-raw'}.jpg?camera=${camera.camera}&frame=${camera.frames}`;}
    }catch(error){$('camera-status').textContent='Camera disconnected';}finally{pending=false;}
  }
  refresh();setInterval(refresh,400);
}
