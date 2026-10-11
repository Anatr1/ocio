'use strict';
const $ = id => document.getElementById(id);
const euro = new Intl.NumberFormat('en-IE', {style: 'currency', currency: 'EUR', maximumFractionDigits: 0});
const num = new Intl.NumberFormat('en-GB', {maximumFractionDigits: 0});
const dec = new Intl.NumberFormat('en-GB', {maximumFractionDigits: 1});
const shortEuro = new Intl.NumberFormat('en-IE', {style:'currency', currency:'EUR', notation:'compact', maximumFractionDigits:2});
const shortNum = new Intl.NumberFormat('en-GB', {notation:'compact', maximumFractionDigits:1});
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const signed = v => v < 0 ? 'negative' : 'positive';
const icons = () => window.lucide?.createIcons();
const baselineNames = {button:'Demand-actuated / button', fixed:'Simulator fixed cycle', beacon:'Beacon only'};
const advanced = [
 ['crossing_length_m','Crossing length (m)',4,30,.5], ['active_days','Traffic-profile days / year',0,365,1],
 ['occupancy','Vehicle occupancy (people)',1,5,.1], ['seed','Random seed',0,100000,1],
 ['power_watts','Device average power (W)',0,1000,1], ['electricity_eur_kwh','Electricity (EUR / kWh)',0,5,.01],
 ['grid_kg_kwh','Grid emissions (kg CO2 / kWh)',0,2,.001], ['idle_lph','Petrol/diesel idle rate (L / h)',0,10,.1],
 ['fuel_eur_l','Petrol/diesel fuel price (EUR / L)',0,10,.001], ['combustion_kg_l','Combustion emissions (kg CO2 / L)',0,5,.01],
 ['ice_fraction','Modelled petrol/diesel fleet share (%)',0,100,1,true], ['engine_running_fraction','Engine running while queued (%)',0,100,5,true],
 ['supplier_setup_cost_eur','Supplier product setup budget (EUR)',0,10000000,1000],
 ['supplier_discount_rate','Supplier appraisal discount rate (%)',0,50,1,true],
];
let dataset, parameters, trafficData, costProfiles, selected = new Set(), overrides = {}, map, geoLayer, roadLayer;
let layers = new Map(), lastResult, lastJob, busy = false, currentView = 'deployment';
let charts = {}, saved = [];
try { saved = JSON.parse(localStorage.getItem('occhio-turin-district-comparisons-v1') || '[]').slice(-8); } catch (_) {}

function showView(name) {
  currentView = name;
  document.querySelectorAll('.view').forEach(el => el.classList.toggle('active', el.id === name));
  document.querySelectorAll('.tabs button').forEach(el => el.classList.toggle('active', el.dataset.view === name));
  if (name === 'deployment') setTimeout(() => map?.invalidateSize(), 30);
}
function error(message) { $('notice').textContent = message; $('notice').hidden = !message; }
function pValues() {
  const p = {...parameters};
  Object.keys(p).forEach(key => {
    const input = $(key);
    if (!input) return;
    if (input.type === 'checkbox') p[key] = input.checked;
    else if (input.tagName === 'SELECT') p[key] = input.value;
    else p[key] = Number(input.value) / (input.hasAttribute('data-percent') ? 100 : 1);
  });
  p.traffic_level = document.querySelector('[name="traffic_level"]:checked')?.value || p.traffic_level;
  p.priority = document.querySelector('[name="priority"]:checked')?.value || p.priority || 'co2';
  p.vehicle_vph = trafficData.presets[p.traffic_level].vehicle_vph;
  p.use_observed_traffic = false;
  p.inventory_mode = 'mapped';
  // The model stores delivery cost; the form accepts the final installed price.
  p.installed_cost_eur = Number($('installed_price_eur').value) * (1 - p.supplier_gross_margin);
  p.annual_maintenance_eur = Number($('maintenance_fee_eur').value) * (1 - p.supplier_gross_margin);
  p.replacement_schedule = 'spread';
  return p;
}
function setInputs(values) {
  Object.entries(values).forEach(([key,value]) => {
    const input = $(key);
    if (!input) return;
    if (input.type === 'checkbox') input.checked = value;
    else {
      if(input.type==='number'&&!['seed','horizon_years','replacement_year'].includes(key))input.step='any';
      input.value = input.hasAttribute('data-percent') ? Number((value * 100).toFixed(5)) : value;
    }
  });
  const radio = document.querySelector(`[name="traffic_level"][value="${values.traffic_level}"]`);
  if(radio)radio.checked=true;
  const priorityRadio = document.querySelector(`[name="priority"][value="${values.priority || 'co2'}"]`);
  if(priorityRadio)priorityRadio.checked=true;
  if(Object.hasOwn(values,'installed_cost_eur'))$('installed_price_eur').value=(values.installed_cost_eur/(1-values.supplier_gross_margin)).toFixed(2);
  if(Object.hasOwn(values,'annual_maintenance_eur'))$('maintenance_fee_eur').value=(values.annual_maintenance_eur/(1-values.supplier_gross_margin)).toFixed(2);
}
function siteCount(a, p) {
  if (Object.hasOwn(overrides,a.id)) return overrides[a.id];
  const quota = (a.signalized_crossings || 0) * p.installations_per_node;
  return Math.floor(quota * p.coverage_pct / 100 + .5);
}
function selectedAreas() { return dataset.features.map(f => f.properties).filter(a => selected.has(a.id)); }
function renderAreaList() {
  const query = $('search').value.trim().toLocaleLowerCase();
  const areas = dataset.features.map(f => f.properties).filter(a => `${a.name} ${a.zone_name}`.toLocaleLowerCase().includes(query));
  areas.sort((a,b) => Number(selected.has(b.id)) - Number(selected.has(a.id)) || a.name.localeCompare(b.name));
  $('area-list').innerHTML = areas.length ? areas.map(a => `<div class="area-row ${selected.has(a.id) ? 'selected' : ''}"><label class="checkbox" style="flex:1;min-width:0"><input type="checkbox" data-area="${a.id}" ${selected.has(a.id)?'checked':''}><span><strong>${esc(a.name)}</strong><small>${esc(a.zone_name)}</small></span></label></div>`).join('') : '<p class="no-matches">No matching districts or neighbourhoods</p>';
  $('area-list').querySelectorAll('[data-area]').forEach(input => input.onchange = () => {
    input.checked ? selected.add(input.dataset.area) : selected.delete(input.dataset.area);
    delete overrides[input.dataset.area];
    $('area-preset').value = 'custom'; refreshSelection();
  });
}
function refreshSelection(list = true) {
  const areas = selectedAreas(), p = pValues();
  const total = areas.reduce((v,a) => v + a.population,0);
  const count = areas.reduce((v,a) => v + siteCount(a,p),0);
  $('selection-count').textContent = `${areas.length} ${areas.length === 1 ? 'district' : 'districts'}`;
  $('selection-pop').textContent = `${num.format(total)} residents`;
  $('proposed-sites').textContent = num.format(count);
  $('coverage-range').value=p.coverage_pct;
  const potential=areas.reduce((v,a)=>v+siteCount(a,{...p,coverage_pct:100}),0);
  $('coverage-basis').textContent=`${p.coverage_pct}% of approximately ${num.format(potential)} signalized crossings in selected districts. Inventory unverified.`;
  $('cost-preset-summary').innerHTML=`<strong>${euro.format(p.installed_cost_eur/(1-p.supplier_gross_margin))}<small> / crossing</small></strong><span>+ ${euro.format(p.platform_cost_eur)} shared setup</span>`;
  $('cost-preset-note').textContent=p.cost_profile==='pilot' ? 'Conditional on existing pole, power and an approved controller input. No civil works or product certification.' : 'Controller integration and installation allowances included. Not a supplier quote.';
  $('inventory-note').textContent = `${num.format(areas.reduce((v,a) => v+(a.signalized_crossings||0),0))} OpenStreetMap signalized crossing nodes in selected districts x ${p.installations_per_node} crossings/node x coverage percentage, rounded per district. The grouping factor is an assumption, not a surveyed count or verified retrofit compatibility.`;
  $('replacement-note').textContent=`${dec.format(p.replacement_fraction*100)}% across ${p.horizon_years} years, spread as ${dec.format(p.replacement_fraction*100/p.horizon_years)}% per year. Each replacement uses the installed prototype cost.`;
  const other=1-p.work_time_fraction-p.spending_time_fraction;
  $('time-allocation-note').textContent=other < -1e-9 ? 'Work and spending allocations exceed 100%. Reduce one of the shares.' : `${dec.format(p.work_time_fraction*100)}% work, ${dec.format(p.spending_time_fraction*100)}% spending, ${dec.format(Math.max(0,other)*100)}% other time with no GDP contribution. All shares are assumptions.`;
  $('map-coverage').textContent = `${areas.length} of 8 districts selected`;
  layers.forEach((layer,id) => layer.setStyle({color:selected.has(id)?'#087b79':'#a9bcc1',fillColor:selected.has(id)?'#148d85':'#dae5e8',fillOpacity:selected.has(id)?.60:.50,weight:selected.has(id)?1.5:.7}));
  if (list) renderAreaList();
  $('run').disabled = busy || !selected.size;
  $('run-top').disabled = busy || !selected.size;
}
function choosePreset(value) {
  selected.clear(); overrides = {};
  dataset.features.forEach(f => {
    const a = f.properties;
    if (value === 'all' || (value.startsWith('district-') && a.zone === Number(value.slice(9)))) selected.add(a.id);
  });
  refreshSelection();
}
function initMap() {
  map = L.map('map',{preferCanvas:true,zoomSnap:.25,attributionControl:true}).setView([45.07,7.68],11);
  map.attributionControl.setPrefix(false);
  map.attributionControl.addAttribution('<a href="http://geoportale.comune.torino.it/" target="_blank" rel="noopener">Citta di Torino</a>');
  geoLayer = L.geoJSON(dataset,{onEachFeature:(f,layer)=>{
    const a=f.properties;
    layers.set(a.id,layer);
    layer.bindTooltip(`<strong>${esc(a.name)}</strong><br>${esc(a.zone_name)}`,{sticky:true,className:'district-tooltip'});
    layer.on('click',()=>{selected.has(a.id)?selected.delete(a.id):selected.add(a.id);delete overrides[a.id];$('area-preset').value='custom';refreshSelection();});
  }}).addTo(map);
  map.on('resize',()=>{if(map.getSize().x>24&&map.getSize().y>24)map.fitBounds(geoLayer.getBounds(),{padding:[12,12],animate:false});});
  map.fitBounds(geoLayer.getBounds(),{padding:[12,12]});
  map.setMaxBounds(geoLayer.getBounds().pad(.4));
  dataset.features.forEach(f=>{
    const a=f.properties;
    L.marker([a.center[1],a.center[0]],{icon:L.divIcon({className:'district-map-label',html:`<strong>${a.zone}</strong>`,iconSize:[25,25],iconAnchor:[12,12]}),interactive:false}).addTo(map);
  });
  $('fit-map').onclick=()=>map.fitBounds(geoLayer.getBounds(),{padding:[12,12]});
  $('basemap').onchange=()=>{
    if ($('basemap').checked) {
      roadLayer=L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>'}).addTo(map);
      roadLayer.on('tileerror',()=>error('Road tiles are unavailable. District boundaries remain available offline.'));
    } else if(roadLayer) {map.removeLayer(roadLayer);error('');}
  };
}
function chart(id,type,data,extra={}) {
  charts[id]?.destroy();
  charts[id] = new Chart($(id),{type,data,options:{responsive:true,maintainAspectRatio:false,animation:false,
    plugins:{legend:{display:type==='line'||id==='delay-chart',labels:{boxWidth:10,boxHeight:10,font:{size:10},color:'#62757b'}}},
    scales:{x:{grid:{display:false},ticks:{color:'#62757b',font:{size:10}}},y:{grid:{color:'#e5ecee'},ticks:{color:'#62757b',font:{size:10},callback:v=>shortNum.format(v)}}},...extra}});
}
function renderDelayChart() {
  const r=lastResult, mode=$('delay-mode').value;
  const rows=r.experiment;
  chart('delay-chart','bar',{labels:rows.map(v=>v.name),datasets:[{label:'Baseline',data:rows.map(v=>v.baseline[`mean_${mode}_wait_s`]),backgroundColor:'#8cabb8',borderRadius:2},{label:'\u00f2cio adaptive',data:rows.map(v=>v.adaptive[`mean_${mode}_wait_s`]),backgroundColor:'#168b84',borderRadius:2}]});
  $('delay-note').textContent=rows.length ? `Seconds per arrival, including residual queue delay. Reference crossing: ${num.format(r.benchmark_vehicle_vph)} peak vehicles/h, ${num.format(r.parameters.pedestrian_pph)} pedestrians/h; seed ${r.parameters.seed}. Four seeds feed the appraisal.` : 'No causal beacon-only delay benefit modelled.';
}
function renderResult(r,jobId) {
  lastResult=r;lastJob=jobId;
  const t=r.totals;
  const optimization=r.optimization?.[0], choice=optimization?.selected;
  $('optimization-summary').textContent=choice ? `${r.parameters.priority==='co2'?'CO2':'Time'} priority | ${optimization.candidates.length} schedules compared | ${optimization.co2_guardrail_met?'CO2 guardrail met':'CO2 target not achievable'}` : 'No timing benefit modelled';
  const timing=choice?.baseline_fallback ? 'Baseline timing retained: no time benefit.' : choice?.period_timings?.map(v=>`${v.name}: ${v.vehicle_min_green_s}s`).join(' | ') || (choice ? `${choice.vehicle_min_green_s}s vehicle minimum green` : '');
  $('timing-detail').textContent=timing ? `${timing}. ${optimization.shared_optimum ? 'Both priorities select the same best tested schedule.' : 'Vehicle minimum green by demand period.'}` : '';
  const litres=v=>v==null?'Not modelled':`${num.format(v)} L`;
  $('fuel-metrics').innerHTML=`<div>Baseline idle fuel / year<strong>${litres(t.baseline_idle_fuel_litres)}</strong><small>All equipped crossings, not one car or whole-trip fuel</small></div><div>With system / year<strong>${litres(t.adaptive_idle_fuel_litres)}</strong><small>Includes baseline operation during assumed downtime</small></div><div>Idle fuel saved / crossing / year<strong class="${signed(t.fuel_saved_per_crossing_litres??0)}">${litres(t.fuel_saved_per_crossing_litres)}</strong><small>Negative means additional fuel consumption</small></div><div>Engine-on idle reference<strong>${r.parameters.idle_lph.toFixed(2)} L/h</strong><small>${dec.format(r.parameters.idle_lph*1000/60)} mL/min; ${dec.format(r.parameters.ice_fraction*100)}% liquid-fuel share x ${dec.format(r.parameters.engine_running_fraction*100)}% engine-on. Editable assumption, not measured fleet mean.</small></div>`;
  $('results-empty').hidden=true;$('results-body').hidden=false;$('results-dot').hidden=false;
  showView('results');
  $('result-title').textContent=`${num.format(t.sites)} estimated crossings across ${t.area_count} Turin ${t.area_count===1?'district':'districts'}`;
  $('result-subtitle').textContent=`${trafficData.presets[r.parameters.traffic_level]?.label||'Saved traffic scenario'} | ${r.parameters.priority==='time'?'Time':'CO2'} priority | ${costProfiles.profiles[r.parameters.cost_profile]?.label||'Saved cost scenario'} | ${num.format(t.population)} residents | Scenario ${r.id}`;
  const metric=(label,key,format,unit='')=>`<div class="kpi"><p class="kpi-label">${label}</p><strong class="kpi-value ${key==='capital_eur'?'':signed(t[key])}">${format(t[key])}${unit}</strong><p class="kpi-range">${r.sensitivity[key] ? `Sensitivity p10&ndash;p90: ${format(r.sensitivity[key].p10)} to ${format(r.sensitivity[key].p90)}` : `${euro.format(t.capital_per_resident_eur)} per resident &middot; gross planning budget`}</p></div>`;
  $('kpis').innerHTML=metric(`${r.parameters.horizon_years}-year social NPV`,'npv_eur',v=>shortEuro.format(v))+metric('Net operational CO2 saved / year','net_co2_tonnes',v=>dec.format(v),' t')+metric('Road-user hours saved / year','person_hours',v=>shortNum.format(v))+metric('Initial deployment budget','capital_eur',v=>shortEuro.format(v));
  $('accounting-strip').innerHTML=`<div>Annual social net<strong class="${signed(t.annual_social_net_eur)}">${euro.format(t.annual_social_net_eur)}</strong><small>Time + fuel + carbon less running and average replacement costs</small></div><div>Benefit / cost &amp; discounted payback<strong>${t.benefit_cost_ratio==null?'N/A':dec.format(t.benefit_cost_ratio)} &middot; ${t.payback_years==null?'not within horizon':t.payback_years+' years'}</strong><small>Social return, not a municipal financial ROI</small></div><div>Average annual municipal running cost<strong>${euro.format(t.average_annual_running_cost_eur??t.annual_opex_eur)}</strong><small>Includes maintenance, electricity and replacements; not municipal cash savings</small></div><div>GDP contribution scenario / year<strong class="${signed(t.gdp_scenario_eur)}">${t.gdp_scenario_eur==null?'Not calculated':euro.format(t.gdp_scenario_eur)}</strong><small>Gross-value-added proxy under work/spending assumptions; excluded from NPV</small></div>`;
  $('gdp-section').hidden=t.gdp_scenario_eur==null;
  if(t.gdp_scenario_eur!=null)$('gdp-metrics').innerHTML=`<div>Productive work contribution<strong class="${signed(t.work_value_added_eur)}">${euro.format(t.work_value_added_eur)}</strong><small>${dec.format(t.productive_hours_delta)} productive hours x ${euro.format(r.parameters.labour_value_eur_h)} value added/hour</small></div><div>Spending-induced contribution<strong class="${signed(t.spending_value_added_eur)}">${euro.format(t.spending_value_added_eur)}</strong><small>${euro.format(t.gross_spending_delta_eur)} potential spending x ${dec.format(r.parameters.spending_additionality*100)}% net-new share x ${dec.format(r.parameters.domestic_value_added_fraction*100)}% domestic value added</small></div><div>Net-new spending scenario<strong class="${signed(t.net_new_spending_delta_eur)}">${euro.format(t.net_new_spending_delta_eur)}</strong><small>After assumed displacement and work-channel overlap; not itself GDP</small></div><div>Accounting boundary<strong>Conditional, not causal</strong><small>Signed net time changes; no multipliers or net product taxes. Domestic output is not necessarily Turin output.</small></div>`;
  $('lifecycle-title').textContent=`${r.parameters.horizon_years}-year appraisal`;
  $('lifecycle-metrics').innerHTML=`<div>Routine maintenance / year<strong>${euro.format(t.annual_maintenance_cost_eur??t.sites*t.annual_service_fee_eur)}</strong><small>${euro.format(t.annual_service_fee_eur)} per crossing/year; excludes major replacements</small></div><div>Device replacements across horizon<strong>${t.replacement_budget_eur==null?'Not calculated':euro.format(t.replacement_budget_eur)}</strong><small>${dec.format(r.parameters.replacement_fraction*100)}% of units across ${r.parameters.horizon_years} years; ${dec.format(t.expected_replaced_units??0)} expected replacements</small></div><div>Average replacement allowance / year<strong>${euro.format(t.average_annual_replacement_eur??0)}</strong><small>At ${euro.format(t.installed_sale_price_eur)} per replacement; included in cash flows and NPV</small></div><div>Electricity / year<strong>${euro.format(t.annual_electricity_cost_eur??t.electricity_kwh*r.parameters.electricity_eur_kwh)}</strong><small>Separate from routine maintenance and device replacement</small></div>`;
  $('supplier-metrics').innerHTML=`<div>Estimated installed sale price<strong>${euro.format(t.installed_sale_price_eur)} / site</strong><small>${euro.format(r.parameters.installed_cost_eur)} delivery allowance + ${dec.format(r.parameters.supplier_gross_margin*100)}% gross margin</small></div><div>Estimated annual service fee<strong>${euro.format(t.annual_service_fee_eur)} / site</strong><small>${euro.format(t.supplier_annual_service_contribution_eur)} annual service contribution</small></div><div>Supplier contribution NPV<strong class="${signed(t.supplier_contribution_npv_eur)}">${euro.format(t.supplier_contribution_npv_eur)}</strong><small>Less ${euro.format(r.parameters.supplier_setup_cost_eur)} product setup; ${dec.format(r.parameters.supplier_discount_rate*100)}% discount</small></div><div>Supplier break-even scale<strong>${t.supplier_break_even_sites==null?'Not reached':num.format(t.supplier_break_even_sites)+' sites'}</strong><small>Same pricing and service assumptions; excludes sales, tax and financing costs</small></div>`;
  chart('benefit-chart','bar',{labels:['Time value','Fuel','Net carbon','Maintenance','Electricity','Replacements'],datasets:[{data:[t.time_value_eur,t.fuel_saving_eur,t.carbon_value_eur,-t.sites*t.annual_service_fee_eur,-t.electricity_kwh*r.parameters.electricity_eur_kwh,-(t.average_annual_replacement_eur||0)],backgroundColor:['#168b84','#3a6ba0',t.carbon_value_eur<0?'#ba404a':'#779743','#ba404a','#a87827','#8b608d'],borderRadius:2}]});
  chart('cashflow-chart','line',{labels:t.cashflows.map(v=>'Year '+v.year),datasets:[{label:'Cumulative discounted social balance (EUR)',data:t.cashflows.map(v=>v.discounted_cumulative),borderColor:'#168b84',backgroundColor:'#168b8415',fill:true,tension:.1,pointRadius:2,borderWidth:2}]});
  chart('scale-chart','line',{labels:r.scale.map(v=>num.format(v.sites)),datasets:[{label:'Social NPV (EUR)',data:r.scale.map(v=>v.npv_eur),borderColor:'#3a6ba0',tension:0,pointRadius:3,borderWidth:2},{label:'Capital budget (EUR)',data:r.scale.map(v=>v.capital_eur),borderColor:'#a87827',tension:0,pointRadius:3,borderWidth:2}]});
  renderDelayChart();
  const cell=v=>`<td class="${signed(v)}">${dec.format(v)}</td>`;
  const gdpCell=v=>`<td class="${signed(v)}">${v==null?'Not calculated':euro.format(v)}</td>`;
  $('results-table').querySelector('tbody').innerHTML=[...r.areas].sort((a,b)=>b.sites-a.sites).map(a=>`<tr><td>${esc(a.name)}</td><td>${num.format(a.sites)}</td><td>${num.format(a.population)}</td>${cell(a.pedestrian_hours)}${cell(a.vehicle_hours)}${cell(a.net_co2_tonnes)}<td class="${signed(a.annual_social_net_eur)}">${euro.format(a.annual_social_net_eur)}</td>${gdpCell(a.gdp_scenario_eur)}<td>${euro.format(a.capital_eur)}</td></tr>`).join('');
  $('results-table').querySelector('tfoot').innerHTML=`<tr><td>Total, shared cost included</td><td>${num.format(t.sites)}</td><td>${num.format(t.population)}</td>${cell(t.pedestrian_hours)}${cell(t.vehicle_hours)}${cell(t.net_co2_tonnes)}<td>${euro.format(t.annual_social_net_eur)}</td>${gdpCell(t.gdp_scenario_eur)}<td>${euro.format(t.capital_eur)}</td></tr>`;
  $('warnings').innerHTML=r.warnings.map(w=>`<li>${esc(w)}</li>`).join('');
  $('export-csv').href=jobId?`/api/jobs/${jobId}/export.csv`:'#';
  $('export-csv').onclick=jobId?null:event=>{event.preventDefault();const keys=Object.keys(r.areas[0]);const quote=v=>'"'+String(v??'').replaceAll('"','""')+'"';download('\ufeff'+[keys.join(','),...r.areas.map(a=>keys.map(k=>quote(a[k])).join(','))].join('\r\n'),'ocio-turin-districts.csv','text/csv');};
  renderComparisons();icons();
}
function download(value, name, type) {
  const url=URL.createObjectURL(new Blob([value],{type})),a=document.createElement('a');
  a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
async function run() {
  error('');
  const formInputs=[...document.querySelectorAll('#deployment input[type=number],#settings input[type=number]')];
  const invalid=formInputs.find(i=>!i.checkValidity()||i.value==='');
  if(invalid){if(invalid.closest('#settings')){showView('settings');invalid.closest('details')?.setAttribute('open','');}invalid.reportValidity();return;}
  const payload={areas:[...selected],parameters:pValues(),site_overrides:overrides};
  if(payload.parameters.work_time_fraction+payload.parameters.spending_time_fraction>1+1e-9){showView('settings');error('Work and spending time shares must total no more than 100%.');return;}
  busy=true;refreshSelection(false);$('progress').hidden=false;$('run').querySelector('span').textContent='Simulating...';$('run-top').querySelector('span').textContent='Simulating...';
  try {
    const response=await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const body=await response.json();if(!response.ok)throw new Error(body.error||'Unable to run the scenario');
    lastJob=body.job_id;
    while(true){
      const stateResponse=await fetch(`/api/jobs/${lastJob}`);const state=await stateResponse.json();
      if(!stateResponse.ok)throw new Error(state.error||'Simulation status unavailable');
      $('progress').querySelector('progress').value=state.progress||0;
      $('progress').querySelector('span').textContent=state.message||'Running';
      if(state.status==='error')throw new Error(state.error);
      if(state.status==='complete'){renderResult(state.result,lastJob);break;}
      await new Promise(resolve=>setTimeout(resolve,600));
    }
  }catch(e){error(e.message);}finally{busy=false;$('progress').hidden=true;$('run').querySelector('span').textContent='Run simulation';$('run-top').querySelector('span').textContent='Run simulation';refreshSelection(false);}
}
function renderComparisons() {
  $('comparison-section').hidden=!saved.length;
  $('comparison-table').querySelector('tbody').innerHTML=saved.map((r,i)=>{const t=r.totals;return `<tr><td class="comparison-name">${esc(r.label)}<br><small>${esc(r.id)}</small></td><td>${num.format(t.sites)}</td><td>${euro.format(t.capital_eur)}</td><td class="${signed(t.annual_social_net_eur)}">${euro.format(t.annual_social_net_eur)}</td><td class="${signed(t.npv_eur)}">${euro.format(t.npv_eur)}</td><td>${dec.format(t.net_co2_tonnes)} t</td><td><button class="icon" data-load="${i}" aria-label="Show saved scenario" title="Show saved results"><i data-lucide="folder-open"></i></button></td></tr>`;}).join('');
  $('comparison-table').querySelectorAll('[data-load]').forEach(b=>b.onclick=()=>renderResult(saved[Number(b.dataset.load)],null));
  icons();
}
function renderSources(sources) {
  const manifest=sources.find(s=>s.file==='manifest.json')?.data||{};
  const costs=sources.find(s=>s.file==='costs.json')?.data||{};
  const gdp=sources.find(s=>s.file==='gdp_assumptions.json')?.data||{};
  const rows=[...(manifest.sources||[]),...(costs.sources||[]),...(gdp.sources||[])];
  $('source-version').textContent=manifest.dataset_version||'';
  $('source-list').innerHTML=rows.map(s=>`<article class="source-row"><div><h3><a href="${esc(s.url||s.source||'#')}" target="_blank" rel="noopener">${esc(s.title||s.name||s.id)}</a></h3><span class="reference">${esc(s.reference||s.reference_year||s.date||'')}</span><small>${esc(s.license||s.status||'Primary reference / documented assumption')}</small></div><div><p>${esc(s.caveat||s.notes||s.description||'')}</p>${s.sha256?`<span class="hash">Source SHA-256: ${esc(s.sha256)}</span>`:''}</div></article>`).join('');
  $('source-list').innerHTML+=`<div class="small-note">Retrieved ${esc(manifest.retrieved_at||'')}. ${esc((manifest.caveats||[]).join(' '))}</div>`;
  const budget=[...(costs.bom||[]),...(costs.installation||[])];
  $('bom-table').querySelector('tbody').innerHTML=budget.map(b=>`<tr><td title="${esc(b.notes||'')}">${esc(b.name||b.item)}</td><td>${esc(b.quantity??1)} ${esc(b.unit||'')}</td><td>${euro.format((b.cost_eur??b.unit_cost_eur??0)*(b.quantity??1))}</td><td>${b.source?`<a href="${esc(b.source)}" target="_blank" rel="noopener">${esc((b.status||'Source').replaceAll('_',' '))}</a>`:esc((b.status||'Allowance').replaceAll('_',' '))}</td></tr>`).join('')+`<tr><td>20% contingency</td><td></td><td>${euro.format(costs.cost_build_up?.contingency_eur||0)}</td><td>Provisional allowance</td></tr><tr><td><strong>Total installed budget / site</strong></td><td></td><td><strong>${euro.format(costs.defaults?.installed_cost_eur||0)}</strong></td><td>Not a supplier quotation</td></tr>`;
  $('cost-notes').textContent=[costs.price_basis,costs.scope,costs.cost_build_up?.notes,...(costs.excluded_claims||[])].filter(Boolean).join(' ');
  Object.entries(costs.parameter_metadata||{}).forEach(([key,meta])=>{const input=$(key);if(input){input.title=`${meta.status.replaceAll('_',' ')}. ${meta.notes||''}`;input.closest('label').title=input.title;}});
  $('traffic-provenance').innerHTML=`<h2>Three Turin traffic levels</h2><p>${esc(trafficData.caveat)}</p><p>${Object.values(trafficData.presets).map(p=>`${esc(p.label)}: ${num.format(p.vehicle_vph)} vehicles/hour, both directions`).join(' &middot; ')}</p>${(trafficData.sources||[]).map(s=>`<p><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title)}</a> &middot; ${esc(s.reference||s.date||'')}</p>`).join('')}`;
  $('cost-profile-provenance').innerHTML=`<h2>Pilot and production cost boundaries</h2>${Object.values(costProfiles.profiles).map(p=>`<h3>${esc(p.label)}</h3><p>${euro.format(p.parameters.installed_cost_eur)} delivery allowance; ${euro.format(p.parameters.installed_cost_eur/(1-p.parameters.supplier_gross_margin))} estimated sale price; ${euro.format(p.parameters.platform_cost_eur)} shared setup.</p><p>${p.conditions.map(esc).join(' ')}</p>`).join('')}<p>${costProfiles.notes.map(esc).join(' ')}</p>`;
  $('gdp-provenance').innerHTML=`<h2>GDP contribution scenario (gross-value-added proxy)</h2><p>${esc(gdp.status||'No GDP metadata available')}</p>${Object.entries(gdp.formulas||{}).map(([k,v])=>`<p><strong>${esc(k)}</strong>: ${esc(v)}</p>`).join('')}<p>${(gdp.limitations||[]).map(esc).join(' ')}</p>${Object.entries(gdp.parameter_metadata||{}).map(([k,m])=>`<p><strong>${esc(k)}</strong>: ${esc(m.status)}. ${esc(m.notes)}</p>`).join('')}`;
  const mapped=dataset.features.reduce((n,f)=>n+f.properties.signalized_crossings,0);
  const allNodes=dataset.features.reduce((n,f)=>n+f.properties.mapped_crossings,0);
  const potential=dataset.features.reduce((n,f)=>n+siteCount(f.properties,{...parameters,coverage_pct:100}),0);
  $('inventory-provenance').innerHTML=`<h2>What counts as a crossing?</h2><p>A crossing means one assumed location equipped with one &ograve;cio system. Older exports call this a "site". It is not a sensor reading, district or resident.</p><p>The city polygons contain ${num.format(allNodes)} OpenStreetMap crossing nodes, ${num.format(mapped)} tagged as signalized. Nodes are map points, not unique crossing complexes or approved installation locations. The default assumes ${parameters.installations_per_node} equipped crossings per signalized node (one for every four nodes), giving approximately ${num.format(potential)} at 100% city coverage after rounding each district. This grouping is provisional and must be replaced by a surveyed inventory.</p><p>Deployment percentage applies to this estimated signalized inventory in the selected districts, not every painted crosswalk in Turin. Default count formula: round(signalized nodes x ${parameters.installations_per_node} x percentage / 100), summed across selected districts.</p>`;
}
async function init() {
  icons();
  $('advanced-fields').innerHTML=advanced.map(([key,label,min,max,step,percent])=>`<label>${label}<input id="${key}" type="number" min="${min}" max="${max}" step="${step}" ${percent?'data-percent':''}></label>`).join('');
  try{
    const response=await fetch('/api/data');if(!response.ok)throw new Error('Official dataset unavailable');
    const data=await response.json();dataset=data.geography;parameters=data.defaults;trafficData=data.traffic_presets;costProfiles=data.cost_profiles;
    $('traffic-options').innerHTML=['peak','medium','light'].map(key=>{const p=trafficData.presets[key];return `<label class="traffic-option"><input type="radio" name="traffic_level" value="${key}"><span><i data-lucide="car"></i>${esc(p.label)}</span><small>${num.format(p.vehicle_vph)} vehicles / hour</small></label>`;}).join('');
    $('traffic-source-note').textContent=trafficData.short_note;
    setInputs(parameters);
    const mapped=dataset.features.reduce((v,f)=>v+(f.properties.signalized_crossings||0),0);
    $('dataset-summary').textContent=`${dataset.features.length} districts | Turin city only`;
    const zones=[...new Map(dataset.features.map(f=>[f.properties.zone,f.properties.zone_name])).entries()].sort((a,b)=>a[0]-b[0]);
    zones.forEach(([id,name])=>$('area-preset').add(new Option(`Circoscrizione ${id} - ${name}`,`district-${id}`)));
    initMap();choosePreset('all');renderSources(data.sources);renderComparisons();
    document.querySelectorAll('#deployment input:not([data-area]),#deployment select:not(#area-preset),#settings input,#settings select').forEach(input=>{
      if(['search','basemap','cost_profile'].includes(input.id))return;
      input.addEventListener('change',()=>{refreshSelection();});
    });
    $('cost_profile').onchange=()=>{setInputs({...pValues(),...costProfiles.profiles[$('cost_profile').value].parameters});refreshSelection();};
    $('coverage_pct').oninput=()=>refreshSelection(false);
    $('installed_price_eur').oninput=()=>refreshSelection(false);
    $('platform_cost_eur').oninput=()=>refreshSelection(false);
    $('maintenance_fee_eur').oninput=()=>refreshSelection(false);
    $('coverage-range').oninput=()=>{$('coverage_pct').value=$('coverage-range').value;refreshSelection(false);};
    $('area-preset').onchange=()=>{if($('area-preset').value!=='custom')choosePreset($('area-preset').value);};
    $('search').oninput=renderAreaList;
    $('clear').onclick=()=>{selected.clear();overrides={};$('area-preset').value='custom';refreshSelection();};
    $('reset').onclick=()=>{if(busy)return;error('');setInputs(parameters);$('area-preset').value='all';$('search').value='';choosePreset('all');showView('deployment');};
    $('run').onclick=run;
    $('run-top').onclick=run;
    $('delay-mode').onchange=()=>{if(lastResult)renderDelayChart();};
    $('export-json').onclick=()=>{if(lastResult)download(JSON.stringify(lastResult,null,2),`ocio-${lastResult.id}.json`,'application/json');};
    $('save-scenario').onclick=()=>{
      if(!lastResult)return;
      const areaNames=lastResult.areas.length<=2?lastResult.areas.map(a=>a.name).join(', '):`${lastResult.areas.length} Turin districts`;
      saved=saved.filter(s=>s.id!==lastResult.id);saved.push({...lastResult,label:`${areaNames} - ${baselineNames[lastResult.parameters.baseline]}`});saved=saved.slice(-8);
      try{localStorage.setItem('occhio-turin-district-comparisons-v1',JSON.stringify(saved));}catch(_){error('Browser storage is full. Download the scenario JSON to retain it.');}
      renderComparisons();
    };
    $('clear-comparisons').onclick=()=>{saved=[];localStorage.removeItem('occhio-turin-district-comparisons-v1');renderComparisons();};
  }catch(e){error(e.message);$('run').disabled=true;}
  document.querySelectorAll('.tabs button').forEach(b=>b.onclick=()=>showView(b.dataset.view));
  $('back-to-deployment').onclick=()=>showView('deployment');
}
init();
