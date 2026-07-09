#!/usr/bin/env python3
"""Generate a self-contained, rotatable 3D viewer of the LED coordinates.

    venv/bin/python tools/make_viewer.py [coords.csv] [out.html]

Writes a single HTML file (no external dependencies) that draws the 100 LEDs as
a rotatable point cloud with the strand path. This is the seed for the on-screen
simulator — the same coordinates the device uses.
"""
import json
import sys

csv = sys.argv[1] if len(sys.argv) > 1 else "tree/coordinates.csv"
out = sys.argv[2] if len(sys.argv) > 2 else "scratch/tree_viewer.html"

pts = []
for line in open(csv):
    line = line.strip()
    if line:
        x, y, z = line.split(",")
        pts.append([float(x), float(y), float(z)])

TEMPLATE = """<!doctype html>
<meta charset="utf-8">
<title>Mr Tree — LED map</title>
<style>
  html,body{margin:0;height:100%;background:#0b0d10;color:#cfd6dd;font:13px system-ui,sans-serif;overflow:hidden}
  #c{width:100vw;height:100vh;display:block;cursor:grab}
  #c:active{cursor:grabbing}
  #hud{position:fixed;top:10px;left:12px;line-height:1.5;text-shadow:0 1px 2px #000;pointer-events:none}
  #hud b{color:#fff}
  kbd{background:#222;border:1px solid #444;border-radius:3px;padding:0 4px}
</style>
<canvas id="c"></canvas>
<div id="hud"><b>Mr Tree — __N__ LEDs</b><br>drag to rotate · scroll to zoom<br>
<kbd>space</kbd> spin · <kbd>c</kbd> color: <span id="mode">strand</span></div>
<script>
const PTS = __PTS__;
const N = PTS.length;
let cx=0,cy=0,cz=0; for(const p of PTS){cx+=p[0];cy+=p[1];cz+=p[2];} cx/=N;cy/=N;cz/=N;
let ext=1e-6; const C=PTS.map(p=>{const q=[p[0]-cx,p[1]-cy,p[2]-cz];ext=Math.max(ext,Math.hypot(q[0],q[1],q[2]));return q;});
const cv=document.getElementById('c'), ctx=cv.getContext('2d');
let ax=-0.35, ay=0.6, zoom=1, drag=false, lx=0, ly=0, auto=true, mode=0;
const DPR=()=>window.devicePixelRatio||1;
function resize(){cv.width=cv.clientWidth*DPR();cv.height=cv.clientHeight*DPR();}
addEventListener('resize',resize); resize();
cv.addEventListener('mousedown',e=>{drag=true;auto=false;lx=e.clientX;ly=e.clientY;});
addEventListener('mouseup',()=>drag=false);
addEventListener('mousemove',e=>{if(!drag)return;ay+=(e.clientX-lx)*0.01;ax+=(e.clientY-ly)*0.01;lx=e.clientX;ly=e.clientY;});
cv.addEventListener('wheel',e=>{zoom*=Math.exp(-e.deltaY*0.0012);e.preventDefault();},{passive:false});
addEventListener('keydown',e=>{if(e.key===' '){auto=!auto;e.preventDefault();}if(e.key==='c'){mode=1-mode;document.getElementById('mode').textContent=mode?'height':'strand';}});
function col(t){const h=(1-t)*240;return 'hsl('+h+',90%,55%)';}
function draw(){
  if(auto) ay+=0.004;
  const w=cv.width,h=cv.height; ctx.clearRect(0,0,w,h);
  const s=Math.min(w,h)*0.40*zoom/ext;
  const cxx=Math.cos(ax),sxx=Math.sin(ax),cyy=Math.cos(ay),syy=Math.sin(ay);
  const P=C.map((p,i)=>{
    // p = [x, depth, height]. Spin (azimuth) around the vertical HEIGHT axis,
    // then tilt (elevation); screen-vertical is height (up).
    let X = p[0]*cyy - p[1]*syy;   // horizontal after azimuth
    let Yd= p[0]*syy + p[1]*cyy;   // depth after azimuth
    let Z = p[2];                  // height (rotation axis)
    let d = Yd*cxx - Z*sxx;        // depth after elevation (for sort/size)
    let V = Yd*sxx + Z*cxx;        // vertical (height, tilted)
    return {x:w/2+X*s, y:h/2-V*s, d, i, hz:(p[2]/ext+1)/2};
  });
  ctx.strokeStyle='rgba(255,255,255,0.10)'; ctx.lineWidth=DPR();
  ctx.beginPath(); for(let i=0;i<N;i++){const q=P[i]; i?ctx.lineTo(q.x,q.y):ctx.moveTo(q.x,q.y);} ctx.stroke();
  P.slice().sort((a,b)=>a.d-b.d).forEach(q=>{
    const t=mode?q.hz:q.i/(N-1);
    const r=Math.max(2.5,(5+(q.d/ext)*3)*DPR()*Math.sqrt(zoom));
    ctx.beginPath(); ctx.arc(q.x,q.y,r,0,7); ctx.fillStyle=col(t);
    ctx.shadowColor=col(t); ctx.shadowBlur=r*0.8; ctx.fill(); ctx.shadowBlur=0;
  });
  requestAnimationFrame(draw);
}
draw();
</script>
"""

html = TEMPLATE.replace("__PTS__", json.dumps([[round(v, 2) for v in p] for p in pts])).replace("__N__", str(len(pts)))
with open(out, "w") as f:
    f.write(html)
print(f"wrote {out} ({len(pts)} LEDs)")
