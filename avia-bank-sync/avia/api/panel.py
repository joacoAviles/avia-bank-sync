"""Panel técnico mínimo de diagnóstico. No contiene datos; los pide al API con el token."""

HTML = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>AVIA Bank Sync · Panel técnico</title>
<style>
:root{--bg:#0f1115;--fg:#e6e8eb;--mut:#8b93a1;--acc:#ff6a1a;--ok:#3ecf8e;--warn:#f5a524;--err:#f04438;--line:#232733}
body{margin:0;font:14px/1.45 system-ui,sans-serif;background:var(--bg);color:var(--fg)}
header{padding:16px 24px;border-bottom:1px solid var(--line);display:flex;gap:12px;align-items:center}
h1{font-size:16px;margin:0}h1 b{color:var(--acc)}main{padding:24px;display:grid;gap:24px;max-width:1200px}
input,button{font:inherit;background:#171a21;color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:6px 10px}
button{cursor:pointer}button.primary{background:var(--acc);border-color:var(--acc);color:#111}
table{width:100%;border-collapse:collapse}td,th{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{color:var(--mut);font-weight:500}.pill{padding:2px 8px;border-radius:99px;font-size:12px;background:#232733}
.ok{color:var(--ok)}.warning,.authorization_required{color:var(--warn)}.error,.failed{color:var(--err)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}
.card{border:1px solid var(--line);border-radius:8px;padding:12px}.card .v{font-size:20px}.mut{color:var(--mut)}
</style></head><body>
<header><h1><b>AVIA</b> Bank Sync · panel técnico</h1><span class="mut">solo diagnóstico — la operación normal ocurre dentro de Actual</span>
<span style="flex:1"></span><input id="tok" type="password" placeholder="AVIA_API_TOKEN" size="34">
<button onclick="save()">Entrar</button><button class="primary" onclick="sync()">Sincronizar ahora</button></header>
<main><section class="grid" id="kpis"></section>
<section><h3>Conexiones</h3><table id="conns"></table></section>
<section><h3>Conciliación de saldos</h3><table id="rec"></table></section>
<section><h3>Pendiente de revisión</h3><table id="rev"></table></section>
<section><h3>Ejecuciones</h3><table id="runs"></table></section>
<section><h3>Eventos</h3><table id="evs"></table></section></main>
<script>
const T=()=>sessionStorage.getItem('avia_tok')||'';function save(){sessionStorage.setItem('avia_tok',document.getElementById('tok').value);load()}
async function api(p,o={}){const r=await fetch(p,{...o,headers:{'Authorization':'Bearer '+T(),'Content-Type':'application/json'}});if(!r.ok)throw new Error(r.status);return r.json()}
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmt=d=>d?new Date(d).toLocaleString('es-CL'):'—';const clp=n=>n==null?'—':Number(n).toLocaleString('es-CL',{style:'currency',currency:'CLP'});
function table(id,cols,rows){document.getElementById(id).innerHTML='<tr>'+cols.map(c=>'<th>'+c[0]+'</th>').join('')+'</tr>'+(rows.length?rows.map(r=>'<tr>'+cols.map(c=>'<td>'+c[1](r)+'</td>').join('')+'</tr>').join(''):'<tr><td class=mut>Sin datos</td></tr>')}
async function load(){try{const s=await api('/v1/status');
document.getElementById('kpis').innerHTML=[['Estado','<span class="'+s.state+'">'+s.state+'</span>'],['Última sync OK',fmt(s.lastSuccessfulSync)],['Próxima',fmt(s.nextScheduledSync)],['Cuentas vinculadas',s.linkedAccounts],['Movimientos',s.importedTransactions],['Revisión',s.needsReview]].map(k=>'<div class=card><div class=mut>'+k[0]+'</div><div class=v>'+k[1]+'</div></div>').join('');
table('conns',[['Banco',r=>esc(r.bank)],['Nombre',r=>esc(r.label)],['Estado',r=>'<span class="pill '+r.status+'">'+r.status+'</span>'],['Cuentas',r=>r.accounts],['Último éxito',r=>fmt(r.last_success_at)],['Error',r=>esc(r.last_error)]],s.connections);
const rec=(await api('/v1/reconciliation')).accounts;table('rec',[['Cuenta',r=>esc(r.name+' '+(r.masked_number||''))],['Fecha',r=>r.snapshot_date],['Contable banco',r=>clp(r.booked)],['Disponible',r=>clp(r.available)],['Actual (conciliado)',r=>clp(r.actual_calculated)],['Diferencia',r=>r.difference==null?'—':'<span class="'+(Number(r.difference)?'warning':'ok')+'">'+clp(r.difference)+'</span>']],rec);
table('rev',[['Fecha',r=>r.value_date],['Cuenta',r=>esc(r.account)],['Detalle',r=>esc(r.description)],['Monto',r=>clp(r.amount)],['Motivo',r=>esc(r.review_reason)]],(await api('/v1/review')).items);
table('runs',[['Inicio',r=>fmt(r.started_at)],['Origen',r=>r.trigger],['Estado',r=>'<span class="'+r.status+'">'+r.status+'</span>'],['Nuevos',r=>r.stats.new??'—'],['Actualizados',r=>r.stats.updated??'—'],['Pend→Cont',r=>r.stats.pending_booked??'—'],['Revertidos',r=>r.stats.reversed??'—'],['Error',r=>esc(r.error)]],(await api('/v1/runs')).runs);
table('evs',[['Fecha',r=>fmt(r.created_at)],['Nivel',r=>'<span class="'+r.level+'">'+r.level+'</span>'],['Tipo',r=>r.event_type],['Mensaje',r=>esc(r.message)]],(await api('/v1/events?limit=50')).events)}catch(e){document.getElementById('kpis').innerHTML='<div class="card error">No autorizado o servicio caído ('+esc(e.message)+')</div>'}}
async function sync(){await api('/v1/sync',{method:'POST',body:JSON.stringify({trigger:'manual'})});setTimeout(load,1500)}
document.getElementById('tok').value=T();if(T())load();setInterval(()=>T()&&load(),15000);
</script></body></html>"""
