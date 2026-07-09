#!/usr/bin/env python3
"""Generate a drag-to-edit 3D coordinate editor for the LED strand.

    venv/bin/python tools/make_editor.py [coords.csv] [segments.csv] [out.html]

Writes a self-contained HTML tool (no external deps, open the file directly in a
browser) that draws the 100 LEDs as a rotatable point cloud coloured by segment.
Click a bulb to select it (and light it on the board, if the device host is set),
then drag it to reposition in the current screen plane; rotate the view and drag
again to fix depth. Arrow keys nudge by one unit. It never writes to the board or
the CSV -- it accumulates a changeset and hands back a full coordinates.csv for
you to apply on the host with:

    (paste the copied CSV into tree/coordinates.csv)
    venv/bin/python tools/gen_segments.py     # re-derive segments.csv
    ./deploy.sh && curl http://<host>:7433/reboot

Re-run this generator after applying a changeset to verify the new positions.
"""
import json
import sys

coords_path = sys.argv[1] if len(sys.argv) > 1 else "tree/coordinates.csv"
seg_path = sys.argv[2] if len(sys.argv) > 2 else "tree/segments.csv"
out = sys.argv[3] if len(sys.argv) > 3 else "scratch/coord_editor.html"

coords = []
for line in open(coords_path):
    line = line.strip()
    if line:
        x, y, z = line.split(",")
        coords.append([int(float(x)), int(float(y)), int(float(z))])

segs = []
try:
    for line in open(seg_path):
        line = line.strip()
        if line:
            segs.append(int(line))
except OSError:
    segs = [0] * len(coords)
segs += [0] * (len(coords) - len(segs))
segs = segs[: len(coords)]


def dist(a, b):
    return sum((coords[a][k] - coords[b][k]) ** 2 for k in range(3)) ** 0.5


# Calibration hint: user reports bulbs 4 and 92 are accurate and ~2" apart.
scale_note = ""
if len(coords) > 92:
    d = dist(4, 92)
    scale_note = f"bulbs 4&#8596;92 = {d:.0f}u &#8776; 2in, so &#8776;{d/2:.0f} units/inch"

TEMPLATE = """<!doctype html>
<meta charset="utf-8"><title>Mr Tree - coord editor</title>
<style>
 html,body{margin:0;height:100%;background:#0b0d10;color:#cfd6dd;font:13px system-ui,sans-serif;overflow:hidden}
 #c{width:100vw;height:100vh;display:block;cursor:crosshair}
 #hud{position:fixed;top:10px;left:12px;line-height:1.7;text-shadow:0 1px 2px #000;max-width:46em}
 #hud b{color:#fff} kbd{background:#222;border:1px solid #444;border-radius:3px;padding:0 4px}
 input{background:#161a1f;color:#cfd6dd;border:1px solid #333;border-radius:4px;padding:2px 5px;width:150px}
 button{background:#222;color:#cfd6dd;border:1px solid #444;border-radius:4px;padding:2px 8px;cursor:pointer;margin-right:4px}
 #status{color:#7fd18f} #sel{color:#ffd479} #scale{color:#8a8a8a}
 #panel{position:fixed;top:10px;right:12px;width:22em;max-height:92vh;overflow:auto;background:rgba(12,15,18,0.85);border:1px solid #222;border-radius:6px;padding:8px 10px;line-height:1.5}
 #panel h3{margin:0 0 6px;font-size:13px;color:#fff} #changes{white-space:pre;font-family:ui-monospace,monospace;font-size:12px;color:#cfd6dd}
 #panel .row{margin:6px 0}
</style>
<canvas id="c"></canvas>
<div id="hud"><b>Mr Tree - coordinate editor</b><br>
drag empty space to rotate &middot; drag a bulb to move it (screen plane) &middot; arrows nudge 1u &middot; <kbd>shift</kbd>+&#8593;/&#8595; depth &middot; <kbd>0</kbd>-<kbd>4</kbd> set segment &middot; right/shift-drag pan &middot; scroll zoom &middot; <kbd>r</kbd> view reset &middot; <kbd>p</kbd> pin reference<br>
<span style="color:#8a8a8a">&#9679;</span> trunk &nbsp;<span style="color:#ff4d4d">&#9679;</span> br1 &nbsp;<span style="color:#3ddc84">&#9679;</span> br2 &nbsp;<span style="color:#4d9bff">&#9679;</span> br3 &nbsp;<span style="color:#ffcc4d">&#9679;</span> br4 &nbsp; <span id="scale">__SCALE__</span><br>
device <input id="host" value="192.168.50.100:7433"> <button id="clear">clear light</button> <span id="status"></span><br>
<span id="sel">no bulb selected</span></div>
<div id="panel">
 <h3>changeset</h3>
 <div class="row">segment of selected: <button data-seg="0">trunk</button><button data-seg="1">br1</button><button data-seg="2">br2</button><button data-seg="3">br3</button><button data-seg="4">br4</button></div>
 <div class="row"><button id="revert">revert selected</button><button id="revertall">revert all</button></div>
 <div class="row"><button id="copycsv">copy coordinates.csv</button><button id="copydiff">copy pos changeset</button><button id="copyseg">copy segment overrides</button></div>
 <div id="changes">(no changes yet)</div>
</div>
<script>
const ORIG=__COORDS__, SEG0=__SEG__, COL=__COL__, N=ORIG.length;
const EDIT=ORIG.map(p=>p.slice());
const SEG=SEG0.slice();
const SEGNAMES=['trunk','br1','br2','br3','br4'];
let cx=0,cy=0,cz=0; for(const p of ORIG){cx+=p[0];cy+=p[1];cz+=p[2];} cx/=N;cy/=N;cz/=N;
let ext=1e-6; for(const p of ORIG){ext=Math.max(ext,Math.hypot(p[0]-cx,p[1]-cy,p[2]-cz));}
const cv=document.getElementById('c'),ctx=cv.getContext('2d');
let ax=-0.35,ay=0.6,zoom=1,panx=0,pany=0,rot=false,pan=false,movebulb=false,moved=false,lx=0,ly=0,auto=false,sel=-1,ref=-1,lastP=[];
let cxx,sxx,cyy,syy,scl;
const DPR=()=>window.devicePixelRatio||1;
function resize(){cv.width=cv.clientWidth*DPR();cv.height=cv.clientHeight*DPR();}
addEventListener('resize',resize);resize();
cv.addEventListener('contextmenu',e=>e.preventDefault());

// centered view coords for bulb i (using current EDIT position)
function cen(i){return [EDIT[i][0]-cx,EDIT[i][1]-cy,EDIT[i][2]-cz];}
// convert a screen-plane / depth delta (view axes) into a world delta
function worldDelta(dX,dd,dV){
  const dYd=dd*cxx+dV*sxx, dz=-dd*sxx+dV*cxx;
  const dx=dX*cyy+dYd*syy, dy=-dX*syy+dYd*cyy;
  return [dx,dy,dz];
}
function pick(mx,my){
  let best=-1,bd=1e18;
  for(const q of lastP){const dx=q.x-mx,dy=q.y-my,d=dx*dx+dy*dy;if(d<bd){bd=d;best=q.i;}}
  return (best>=0 && bd<(20*DPR())**2)?best:-1;
}
cv.addEventListener('mousedown',e=>{
  const rect=cv.getBoundingClientRect();
  const mx=(e.clientX-rect.left)*DPR(), my=(e.clientY-rect.top)*DPR();
  moved=false;lx=e.clientX;ly=e.clientY;
  if(e.button===2||e.shiftKey){pan=true;return;}
  const hit=pick(mx,my);
  if(hit>=0){select(hit);movebulb=true;}else{rot=true;}
});
addEventListener('mouseup',()=>{rot=false;pan=false;movebulb=false;});
addEventListener('mousemove',e=>{
  const dx=e.clientX-lx,dy=e.clientY-ly;
  if(!rot&&!pan&&!movebulb)return;
  if(Math.abs(dx)+Math.abs(dy)>2)moved=true;
  if(pan){panx+=dx*DPR();pany+=dy*DPR();}
  else if(movebulb&&sel>=0){
    const dX=(dx*DPR())/scl, dV=-(dy*DPR())/scl;   // depth held fixed
    const wd=worldDelta(dX,0,dV);
    EDIT[sel][0]+=wd[0];EDIT[sel][1]+=wd[1];EDIT[sel][2]+=wd[2];
    refresh();
  }else if(rot){ay-=dx*0.01;ax-=dy*0.01;}
  lx=e.clientX;ly=e.clientY;
});
cv.addEventListener('wheel',e=>{
  const rect=cv.getBoundingClientRect();
  const mx=(e.clientX-rect.left)*DPR(), my=(e.clientY-rect.top)*DPR();
  const f=Math.exp(-e.deltaY*0.0012);
  panx=panx*f+(mx-cv.width/2)*(1-f);
  pany=pany*f+(my-cv.height/2)*(1-f);
  zoom*=f;e.preventDefault();
},{passive:false});
addEventListener('keydown',e=>{
  if(e.key===' '){auto=!auto;e.preventDefault();return;}
  if(e.key==='r'){ax=-0.35;ay=0.6;zoom=1;panx=0;pany=0;return;}
  if(e.key==='Escape'){clearLight();return;}
  if(e.key==='p'){ref=sel;refresh();return;}
  if(sel<0)return;
  if(e.key>='0'&&e.key<='4'){setSeg(+e.key);e.preventDefault();return;}
  let dX=0,dd=0,dV=0;
  if(e.key==='ArrowLeft')dX=-1; else if(e.key==='ArrowRight')dX=1;
  else if(e.key==='ArrowUp'){if(e.shiftKey)dd=1;else dV=1;}
  else if(e.key==='ArrowDown'){if(e.shiftKey)dd=-1;else dV=-1;}
  else return;
  e.preventDefault();
  const wd=worldDelta(dX,dd,dV);
  EDIT[sel][0]+=wd[0];EDIT[sel][1]+=wd[1];EDIT[sel][2]+=wd[2];
  refresh();
});
function host(){return document.getElementById('host').value.trim();}
function select(i){
  sel=i;refresh();
  fetch('http://'+host()+'/inspect/'+i,{mode:'no-cors'})
    .then(()=>document.getElementById('status').textContent='lit LED '+i)
    .catch(()=>document.getElementById('status').textContent='sel '+i+' (device not reachable)');
}
function clearLight(){sel=-1;fetch('http://'+host()+'/inspect/off',{mode:'no-cors'}).catch(()=>{});refresh();}
document.getElementById('clear').onclick=clearLight;
document.querySelectorAll('#panel button[data-seg]').forEach(b=>b.onclick=()=>setSeg(+b.dataset.seg));
function setSeg(s){
  if(sel<0){document.getElementById('status').textContent='select a bulb first (click it), then set its segment';return;}
  SEG[sel]=s;refresh();
  document.getElementById('status').textContent='bulb '+sel+' -> '+SEGNAMES[s]+(s!==SEG0[sel]?' (override)':' (back to computed)');
}
document.getElementById('revert').onclick=()=>{if(sel>=0){EDIT[sel]=ORIG[sel].slice();SEG[sel]=SEG0[sel];refresh();}};
document.getElementById('revertall').onclick=()=>{for(let i=0;i<N;i++){EDIT[i]=ORIG[i].slice();SEG[i]=SEG0[i];}refresh();};
document.getElementById('copycsv').onclick=()=>copy(EDIT.map(p=>p.map(Math.round).join(',')).join('\\n')+'\\n','coordinates.csv copied');
document.getElementById('copydiff').onclick=()=>{
  const lines=[];for(let i=0;i<N;i++)if(changed(i))lines.push('bulb '+i+': '+ORIG[i].join(',')+' -> '+EDIT[i].map(Math.round).join(','));
  copy(lines.join('\\n')||'(no changes)','pos changeset copied');
};
document.getElementById('copyseg').onclick=()=>{
  const lines=[];for(let i=0;i<N;i++)if(SEG[i]!==SEG0[i])lines.push('    '+i+': '+SEG[i]+',   # '+SEGNAMES[SEG0[i]]+' -> '+SEGNAMES[SEG[i]]);
  copy(lines.join('\\n')||'(no segment changes)','segment overrides copied');
};
function copy(t,msg){navigator.clipboard.writeText(t).then(()=>document.getElementById('status').textContent=msg).catch(()=>{document.getElementById('status').textContent='copy blocked - select the panel text';});}
function changed(i){return Math.round(EDIT[i][0])!==ORIG[i][0]||Math.round(EDIT[i][1])!==ORIG[i][1]||Math.round(EDIT[i][2])!==ORIG[i][2];}
function refresh(){
  const s=document.getElementById('sel');
  if(sel<0)s.textContent='no bulb selected';
  else{
    const e=EDIT[sel].map(Math.round),o=ORIG[sel];
    let t='bulb '+sel+'  ('+e.join(',')+')  seg '+SEGNAMES[SEG[sel]]+'  was ('+o.join(',')+') '+SEGNAMES[SEG0[sel]];
    if(ref>=0&&ref!==sel){const d=Math.hypot(EDIT[sel][0]-EDIT[ref][0],EDIT[sel][1]-EDIT[ref][1],EDIT[sel][2]-EDIT[ref][2]);t+='   dist to ref '+ref+' = '+d.toFixed(1)+'u';}
    s.textContent=t;
  }
  const lines=[];
  for(let i=0;i<N;i++){
    const cc=changed(i), sc=SEG[i]!==SEG0[i];
    if(!cc&&!sc)continue;
    let l=String(i).padStart(3)+'  ';
    l+=cc?(ORIG[i].join(',')+' -> '+EDIT[i].map(Math.round).join(',')):('pos '+ORIG[i].join(','));
    if(sc)l+='  ['+SEGNAMES[SEG0[i]]+'->'+SEGNAMES[SEG[i]]+']';
    lines.push(l);
  }
  document.getElementById('changes').textContent=lines.length?lines.join('\\n'):'(no changes yet)';
}
function rgb(s){const c=COL[s]||COL[0];return 'rgb('+c[0]+','+c[1]+','+c[2]+')';}
function draw(){
 if(auto)ay+=0.004;
 const w=cv.width,h=cv.height;ctx.clearRect(0,0,w,h);
 scl=Math.min(w,h)*0.40*zoom/ext;
 cxx=Math.cos(ax);sxx=Math.sin(ax);cyy=Math.cos(ay);syy=Math.sin(ay);
 const P=[];
 for(let i=0;i<N;i++){
   const p=cen(i);
   const X=p[0]*cyy-p[1]*syy, Yd=p[0]*syy+p[1]*cyy, Z=p[2];
   const d=Yd*cxx-Z*sxx, V=Yd*sxx+Z*cxx;
   P.push({x:w/2+panx+X*scl,y:h/2+pany-V*scl,d,i,seg:SEG[i]});
 }
 lastP=P;
 ctx.strokeStyle='rgba(255,255,255,0.08)';ctx.lineWidth=DPR();
 ctx.beginPath();for(let i=0;i<N;i++){const q=P[i];i?ctx.lineTo(q.x,q.y):ctx.moveTo(q.x,q.y);}ctx.stroke();
 const fs=Math.round(11*DPR()*Math.sqrt(zoom));
 ctx.font=fs+'px system-ui';ctx.textBaseline='middle';
 P.slice().sort((a,b)=>a.d-b.d).forEach(q=>{
   const r=Math.max(2.5,(5+(q.d/ext)*3)*DPR()*Math.sqrt(zoom));
   const edited=changed(q.i)||SEG[q.i]!==SEG0[q.i];
   ctx.beginPath();ctx.arc(q.x,q.y,r,0,7);ctx.fillStyle=rgb(q.seg);
   ctx.shadowColor=rgb(q.seg);ctx.shadowBlur=r*0.8;ctx.fill();ctx.shadowBlur=0;
   if(edited){ctx.lineWidth=2*DPR();ctx.strokeStyle='#fff';ctx.beginPath();ctx.arc(q.x,q.y,r+2*DPR(),0,7);ctx.stroke();}
   if(q.i===ref){ctx.lineWidth=2*DPR();ctx.strokeStyle='#ffd479';ctx.beginPath();ctx.arc(q.x,q.y,r+5*DPR(),0,7);ctx.stroke();}
   if(q.i===sel){ctx.lineWidth=3*DPR();ctx.strokeStyle='#7fd18f';ctx.beginPath();ctx.arc(q.x,q.y,r+4*DPR(),0,7);ctx.stroke();}
   const tx=q.x+r+2*DPR();
   ctx.lineWidth=3*DPR();ctx.strokeStyle='rgba(0,0,0,0.85)';ctx.strokeText(q.i,tx,q.y);
   ctx.fillStyle=edited?'#fff':'#eef';ctx.fillText(q.i,tx,q.y);
 });
 requestAnimationFrame(draw);
}
refresh();draw();
</script>
"""

COL = [[138, 138, 138], [255, 77, 77], [61, 220, 132], [77, 155, 255], [255, 204, 77]]
html = (
    TEMPLATE.replace("__COORDS__", json.dumps(coords))
    .replace("__SEG__", json.dumps(segs))
    .replace("__COL__", json.dumps(COL))
    .replace("__SCALE__", scale_note)
)
with open(out, "w") as f:
    f.write(html)
print(f"wrote {out} ({len(coords)} LEDs, {sum(1 for s in segs if s==0)} trunk)")
