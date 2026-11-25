// Shared player for the animated request flows.
// A page defines window.FLOW = {height, rows, nodes, waypoints, steps} and loads this file.
(function () {
  const F = window.FLOW;
  const W = 168, H = 58;
  const KIND = {
    front: {name: 'Frontend', c: '--front', bg: '--front-bg'},
    entry: {name: 'Entry layer', c: '--entry', bg: '--entry-bg'},
    flow:  {name: 'Workflows layer', c: '--flow', bg: '--flow-bg'},
    svc:   {name: 'Services layer', c: '--svc', bg: '--svc-bg'},
    hdl:   {name: 'Handlers layer', c: '--hdl', bg: '--hdl-bg'},
    ext:   {name: 'Outside program', c: '--ext', bg: '--ext-bg'}
  };
  const rowOf = {};
  F.rows.forEach((r, i) => { rowOf[r.key] = i; });

  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.getElementById('stage');
  svg.setAttribute('viewBox', `0 0 1000 ${F.height}`);
  const el = (tag, attrs, parent) => {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    (parent || svg).appendChild(e);
    return e;
  };

  const bands = F.rows.map(r => {
    const g = el('g', {class: 'band'});
    el('rect', {x: 8, y: r.y - 50, width: 984, height: 100, rx: 12}, g);
    el('text', {x: 984, y: r.y - 36, 'text-anchor': 'end'}, g).textContent = r.label;
    return g;
  });
  if (F.boundaryY) {
    el('line', {x1: 8, x2: 992, y1: F.boundaryY, y2: F.boundaryY, class: 'boundary'});
  }

  const N = {};
  for (const id in F.nodes) {
    const n = F.nodes[id];
    N[id] = {...n, y: F.rows[rowOf[n.row]].y};
  }
  const center = id => [N[id].x, N[id].y];
  const WP = F.waypoints || {};
  function route(a, b) {
    const A = center(a), B = center(b);
    if (WP[a + '>' + b]) return [A, ...WP[a + '>' + b], B];
    if (WP[b + '>' + a]) return [A, ...[...WP[b + '>' + a]].reverse(), B];
    if (A[1] === B[1] || A[0] === B[0]) return [A, B];
    const mid = (A[1] + B[1]) / 2;
    return [A, [A[0], mid], [B[0], mid], B];
  }
  const key = (a, b) => [a, b].sort().join('|');

  const edgeLayer = el('g', {});
  const edges = {};
  F.steps.forEach(s => {
    for (let i = 0; i < s.p.length - 1; i++) {
      const k = key(s.p[i], s.p[i + 1]);
      if (edges[k]) continue;
      const [a, b] = k.split('|');
      edges[k] = el('polyline', {points: route(a, b).map(p => p.join(',')).join(' '), class: 'edge'}, edgeLayer);
    }
  });

  const backs = el('g', {});
  const nodes = {};
  for (const id in N) {
    const n = N[id];
    el('rect', {x: n.x - W / 2, y: n.y - H / 2, width: W, height: H, rx: 9, fill: 'var(--bg)'}, backs);
    const g = el('g', {class: 'node k-' + n.row});
    el('rect', {class: 'halo', x: n.x - W / 2 - 4, y: n.y - H / 2 - 4, width: W + 8, height: H + 8, rx: 12}, g);
    el('rect', {class: 'box', x: n.x - W / 2, y: n.y - H / 2, width: W, height: H, rx: 9}, g);
    el('text', {class: 't', x: n.x, y: n.y - 5, 'text-anchor': 'middle'}, g).textContent = n.t;
    el('text', {class: 's', x: n.x, y: n.y + 15, 'text-anchor': 'middle'}, g).textContent = n.s;
    nodes[id] = g;
  }
  const ring = el('circle', {id: 'pktRing', cx: -50, cy: -50, r: 8});
  const pkt = el('circle', {id: 'pkt', cx: -50, cy: -50, r: 7});

  const steps = F.steps;
  let idx = 0, playing = true, raf = 0, timer = 0;
  const speedSel = document.getElementById('speed');
  const speed = () => parseFloat(speedSel.value);
  const bar = document.getElementById('bar');
  steps.forEach((s, i) => {
    const b = document.createElement('i');
    b.title = `Step ${i + 1}` + (s.phase ? `: ${s.phase}` : '');
    if (i > 0 && s.phase) b.classList.add('split');
    b.onclick = () => { setPlaying(false); go(i); };
    bar.appendChild(b);
  });

  function currentPhase(i) {
    for (let j = i; j >= 0; j--) if (steps[j].phase) return steps[j].phase;
    return '';
  }

  function show(i) {
    cancelAnimationFrame(raf);
    clearTimeout(timer);
    const s = steps[i];
    const last = s.p[s.p.length - 1];
    const kind = KIND[N[last].row];

    for (const id in nodes) nodes[id].setAttribute('class', 'node k-' + N[id].row + ' dim');
    for (const k in edges) edges[k].setAttribute('class', 'edge');
    bands.forEach((b, r) => b.setAttribute('class', 'band' + (r === rowOf[N[last].row] ? ' on' : '')));
    for (let j = 0; j < s.p.length - 1; j++) {
      const e = edges[key(s.p[j], s.p[j + 1])];
      e.setAttribute('class', 'edge hot');
      edgeLayer.appendChild(e);
    }

    document.getElementById('count').textContent = `Step ${i + 1} of ${steps.length}`;
    document.getElementById('phase').textContent = currentPhase(i);
    const chip = document.getElementById('chip');
    chip.textContent = kind.name;
    chip.style.background = `var(${kind.bg})`;
    chip.style.color = `var(${kind.c})`;
    document.getElementById('caption').textContent = s.c;
    document.getElementById('data').textContent = s.d || '';
    [...bar.children].forEach((b, j) => {
      b.classList.toggle('done', j < i);
      b.classList.toggle('cur', j === i);
    });

    const hit = id => nodes[id].setAttribute('class', 'node k-' + N[id].row + (id === last ? ' on' : ''));

    const pts = [center(s.p[0])], marks = [{at: 0, id: s.p[0]}];
    for (let j = 0; j < s.p.length - 1; j++) {
      pts.push(...route(s.p[j], s.p[j + 1]).slice(1));
      marks.push({at: pts.length - 1, id: s.p[j + 1]});
    }
    const lens = [0];
    for (let j = 1; j < pts.length; j++) lens.push(lens[j - 1] + Math.hypot(pts[j][0] - pts[j - 1][0], pts[j][1] - pts[j - 1][1]));
    const total = lens[lens.length - 1];
    const dur = total ? Math.max(450, total / 0.8) / speed() : 0;

    hit(s.p[0]);
    pkt.classList.remove('gone');
    const finish = () => {
      pkt.classList.add('gone');
      ring.setAttribute('cx', center(last)[0]);
      ring.setAttribute('cy', center(last)[1]);
      ring.classList.remove('pulse'); void ring.getBBox(); ring.classList.add('pulse');
      if (playing) {
        const dwell = 1300 + s.c.length * 14;
        if (i < steps.length - 1) timer = setTimeout(() => go(i + 1), dwell / speed());
        else setPlaying(false, true);
      }
    };
    if (!total) {
      pkt.setAttribute('cx', center(last)[0]);
      pkt.setAttribute('cy', center(last)[1]);
      hit(last);
      finish();
      return;
    }
    const t0 = performance.now();
    let nextMark = 1;
    const frame = now => {
      const t = Math.min(1, (now - t0) / dur);
      const e = t < .5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
      const d = e * total;
      let j = 1;
      while (j < lens.length - 1 && lens[j] < d) j++;
      const f = (d - lens[j - 1]) / ((lens[j] - lens[j - 1]) || 1);
      pkt.setAttribute('cx', pts[j - 1][0] + (pts[j][0] - pts[j - 1][0]) * f);
      pkt.setAttribute('cy', pts[j - 1][1] + (pts[j][1] - pts[j - 1][1]) * f);
      while (nextMark < marks.length && d >= lens[marks[nextMark].at] - 0.5) { hit(marks[nextMark].id); nextMark++; }
      if (t < 1) raf = requestAnimationFrame(frame); else finish();
    };
    raf = requestAnimationFrame(frame);
  }

  function go(i) { idx = Math.max(0, Math.min(steps.length - 1, i)); show(idx); }

  const playBtn = document.getElementById('play');
  function setPlaying(p, ended) {
    playing = p;
    playBtn.textContent = p ? 'Pause' : (ended ? 'Replay' : 'Play');
    if (!p) clearTimeout(timer);
  }
  playBtn.onclick = () => {
    if (playing) { setPlaying(false); return; }
    const restart = playBtn.textContent === 'Replay';
    setPlaying(true);
    go(restart ? 0 : (idx < steps.length - 1 ? idx + 1 : 0));
  };
  document.getElementById('prev').onclick = () => { setPlaying(false); go(idx - 1); };
  document.getElementById('next').onclick = () => { setPlaying(false); go(idx + 1); };
  document.addEventListener('keydown', e => {
    if (e.target.tagName === 'SELECT') return;
    if (e.code === 'Space') { e.preventDefault(); playBtn.click(); }
    if (e.key === 'ArrowRight') { setPlaying(false); go(idx + 1); }
    if (e.key === 'ArrowLeft') { setPlaying(false); go(idx - 1); }
  });

  go(0);
})();
