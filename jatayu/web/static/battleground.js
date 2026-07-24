/* ════════════════════════════════════════════════════════════════
   JATAYU OS — battleground.js (V2 Phoenix · Maha Meru · Deep Space)
   
   Features:
   - Screen-spanning extended Phoenix Wings (exact initial golden ratio)
   - Perfectly centered WebGL viewport across 100vw
   - Smooth normal-speed spinning Orb core & accretion disk
   - 3D Maha Meru Shri Yantra lattice with lotus petals & bhupura citadel
   - Integrated state transitions (idle, listening, thinking, speaking, alert)
   ════════════════════════════════════════════════════════════════ */

import * as THREE from "three";

const STATES = {
  idle:      { color: 0xF5C76A, rot: 0.0015, swirl: 2.8, wing: 1.0,  flap: 0.35, pulse: 0, label: 'ADVANCED AGI — IDLE' },
  listening: { color: 0x7FD7FF, rot: 0.0035, swirl: 5.0, wing: 1.12, flap: 0.6,  pulse: 0, label: 'ADVANCED AGI — LISTENING' },
  thinking:  { color: 0xFFA93D, rot: 0.012,  swirl: 12.0, wing: 1.05, flap: 1.2,  pulse: 0, label: 'ADVANCED AGI — THINKING' },
  speaking:  { color: 0xFFE7A8, rot: 0.006,  swirl: 7.0, wing: 1.1,  flap: 0.8,  pulse: 1, label: 'ADVANCED AGI — SPEAKING' },
  alert:     { color: 0xE14B4B, rot: 0.0004, swirl: 3.0, wing: 0.92, flap: 0.15, pulse: 0, label: 'ADVANCED AGI — ALERT' },
};

function softTexture(inner = 0.9, mid = 0.25) {
  const c = document.createElement('canvas'); c.width = c.height = 128;
  const x = c.getContext('2d');
  const g = x.createRadialGradient(64, 64, 0, 64, 64, 64);
  g.addColorStop(0, `rgba(255,255,255,${inner})`);
  g.addColorStop(0.4, `rgba(255,255,255,${mid})`);
  g.addColorStop(1, 'rgba(255,255,255,0)');
  x.fillStyle = g; x.fillRect(0, 0, 128, 128);
  return new THREE.CanvasTexture(c);
}

const softTex = softTexture();

const S = {
  container: null,
  getAudioLevel: null,
  running: false,
  inited: false,

  stateName: 'idle',
  target: STATES.idle,
  current: {
    color: new THREE.Color(STATES.idle.color),
    rot: STATES.idle.rot,
    swirl: STATES.idle.swirl,
    wing: STATES.idle.wing,
    flap: STATES.idle.flap
  },

  clusterHealth: { google: "healthy", comms: "healthy", knowledge: "healthy", voice: "healthy" },

  scene: null,
  camera: null,
  renderer: null,
  clock: null,
  rafId: null,
  resizeObserver: null,

  // Camera Orbit — Perfectly centered
  camTheta: 0.5,
  camPhi: 1.3,
  camRadius: 22,
  dragging: false,
  lastX: 0,
  lastY: 0,

  // Objects & Materials
  coreGroup: null,
  yantra: null,
  bhupura: null,
  orbGroup: null,
  glowSprite: null,
  coreLight: null,
  diskUniforms: null,
  wingsGroup: null,
  wingL: null,
  wingR: null,
  featherMats: [],
  emberGeo: null,
  emberMat: null,
  emberSeed: null,
  emberCount: 260,
  ringMats: [],
  galaxy: null,
  nebulaGroup: null,
  lineMat: null,
};

function featherShape(len, width) {
  const s = new THREE.Shape();
  s.moveTo(0, 0);
  s.bezierCurveTo(width, len * 0.25, width * 0.85, len * 0.7, 0, len);
  s.bezierCurveTo(-width * 0.55, len * 0.72, -width * 0.6, len * 0.3, 0, 0);
  return s;
}

function circlePts(r, seg = 72) {
  const pts = []; for (let i = 0; i <= seg; i++) { const a = (i / seg) * Math.PI * 2; pts.push(new THREE.Vector3(r * Math.cos(a), r * Math.sin(a), 0)); } return pts;
}

function addLineTo(group, points, closed = false, mat = S.lineMat) {
  const geo = new THREE.BufferGeometry().setFromPoints(points);
  const line = closed ? new THREE.LineLoop(geo, mat) : new THREE.Line(geo, mat);
  group.add(line); return line;
}

function trianglePts(h, upward) {
  const pts = upward
    ? [[0, h], [-h * 0.866, -h * 0.5], [h * 0.866, -h * 0.5]]
    : [[0, -h], [-h * 0.866, h * 0.5], [h * 0.866, h * 0.5]];
  pts.push(pts[0]);
  return pts.map(p => new THREE.Vector3(p[0], p[1], 0));
}

function buildPhoenixWing(side) {
  const wing = new THREE.Group();
  // Exact initial golden ratio proportions
  const spine = new THREE.CubicBezierCurve3(
    new THREE.Vector3(side * 3.4, -0.4, 0),
    new THREE.Vector3(side * 6.2, 0.6, -0.5),
    new THREE.Vector3(side * 8.6, 2.6, -1.0),
    new THREE.Vector3(side * 10.4, 5.4, -1.4)
  );

  const ranks = [
    { n: 14, len: 1.1, w: 0.16, z: 0.32, droop: 0.55, op: 0.5 },
    { n: 16, len: 2.1, w: 0.2,  z: 0.0,  droop: 0.8,  op: 0.75 },
    { n: 18, len: 3.4, w: 0.24, z: -0.34, droop: 1.05, op: 1.0 },
  ];

  ranks.forEach((rank) => {
    for (let i = 0; i < rank.n; i++) {
      const t = i / (rank.n - 1);
      const p = spine.getPoint(t);
      const len = rank.len * (0.55 + t * 1.05) * (1 - 0.08 * Math.sin(t * Math.PI));
      const geo = new THREE.ExtrudeGeometry(featherShape(len, rank.w * (0.8 + t * 0.5)), { depth: 0.035, bevelEnabled: false });
      const mat = new THREE.MeshStandardMaterial({
        color: 0x120c06,
        emissive: S.current.color, emissiveIntensity: 0.7 + t * 1.3,
        metalness: 0.3, roughness: 0.45,
        transparent: true, opacity: (0.3 + t * 0.65) * rank.op
      });
      S.featherMats.push({ mat, heat: 0.7 + t * 1.3 });
      const f = new THREE.Mesh(geo, mat);
      f.position.set(p.x, p.y, p.z + rank.z);

      const outAngle = THREE.MathUtils.lerp(-rank.droop, 0.85, t);
      f.rotation.z = side > 0 ? (-Math.PI / 2 + outAngle) : (Math.PI / 2 - outAngle);
      f.rotation.y = side * (0.18 - t * 0.1);
      f.rotation.x = -0.12 + Math.sin(t * Math.PI) * 0.1;
      f.userData.baseRotZ = f.rotation.z;
      f.userData.t = t;
      f.userData.side = side;
      wing.add(f);
    }
  });

  const spinePts = spine.getPoints(40);
  addLineTo(wing, spinePts, false, new THREE.LineBasicMaterial({ color: S.current.color, transparent: true, opacity: 0.85 }));
  wing.userData.side = side;
  return wing;
}

function buildScene() {
  S.scene = new THREE.Scene();
  S.scene.background = new THREE.Color(0x020208);
  S.scene.fog = new THREE.FogExp2(0x020208, 0.004);

  S.camera = new THREE.PerspectiveCamera(45, window.innerWidth / window.innerHeight, 0.1, 400);

  S.scene.add(new THREE.AmbientLight(0xffffff, 0.22));
  const keyLight = new THREE.PointLight(0xffe2b0, 1.6, 80);
  keyLight.position.set(8, 10, 12);
  S.scene.add(keyLight);

  S.coreLight = new THREE.PointLight(0xffc860, 2.8, 35);
  S.scene.add(S.coreLight);

  // 1. Deep Space Stars Shell
  {
    const n = 5000;
    const pos = new Float32Array(n * 3), col = new Float32Array(n * 3);
    const palette = [new THREE.Color(0xffffff), new THREE.Color(0xcfe4ff), new THREE.Color(0xffe6c0), new THREE.Color(0xffc9a0)];
    for (let i = 0; i < n; i++) {
      const r = 60 + Math.random() * 120;
      const th = Math.random() * Math.PI * 2, ph = Math.acos(2 * Math.random() - 1);
      pos[i * 3] = r * Math.sin(ph) * Math.cos(th);
      pos[i * 3 + 1] = r * Math.cos(ph);
      pos[i * 3 + 2] = r * Math.sin(ph) * Math.sin(th);
      const c = palette[(Math.random() * palette.length) | 0];
      col[i * 3] = c.r; col[i * 3 + 1] = c.g; col[i * 3 + 2] = c.b;
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    geo.setAttribute('color', new THREE.BufferAttribute(col, 3));
    const mat = new THREE.PointsMaterial({ size: 0.45, map: softTex, vertexColors: true, transparent: true, opacity: 0.9, depthWrite: false, blending: THREE.AdditiveBlending });
    S.scene.add(new THREE.Points(geo, mat));
  }

  // 2. Spiral Galaxy Band
  {
    const n = 9000, arms = 3;
    const pos = new Float32Array(n * 3), col = new Float32Array(n * 3);
    const inner = new THREE.Color(0xffd9a0), outer = new THREE.Color(0x7a6bff);
    for (let i = 0; i < n; i++) {
      const t = Math.random();
      const radius = Math.pow(t, 0.6) * 55;
      const armAngle = ((i % arms) / arms) * Math.PI * 2;
      const spin = radius * 0.12;
      const spread = (Math.random() - 0.5) * (1.5 + radius * 0.14);
      const a = armAngle + spin + spread * 0.12;
      pos[i * 3] = Math.cos(a) * radius + (Math.random() - 0.5) * 2;
      pos[i * 3 + 1] = (Math.random() - 0.5) * (2.4 - t * 1.6);
      pos[i * 3 + 2] = Math.sin(a) * radius + (Math.random() - 0.5) * 2;
      const c = inner.clone().lerp(outer, t);
      col[i * 3] = c.r; col[i * 3 + 1] = c.g; col[i * 3 + 2] = c.b;
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    geo.setAttribute('color', new THREE.BufferAttribute(col, 3));
    const mat = new THREE.PointsMaterial({ size: 0.35, map: softTex, vertexColors: true, transparent: true, opacity: 0.5, depthWrite: false, blending: THREE.AdditiveBlending });
    S.galaxy = new THREE.Points(geo, mat);
    S.galaxy.position.set(-20, 14, -90);
    S.galaxy.rotation.set(1.15, 0.2, 0.5);
    S.scene.add(S.galaxy);
  }

  // 3. Nebulae Sprites
  S.nebulaGroup = new THREE.Group();
  {
    const colors = [0x5b2d8f, 0x1f4d6e, 0x8f4d1f, 0x3a1f6e, 0x145a52];
    for (let i = 0; i < 70; i++) {
      const mat = new THREE.SpriteMaterial({
        map: softTexture(0.16, 0.05), color: colors[(Math.random() * colors.length) | 0],
        transparent: true, opacity: 0.22 + Math.random() * 0.15,
        depthWrite: false, blending: THREE.AdditiveBlending
      });
      const s = new THREE.Sprite(mat);
      const r = 55 + Math.random() * 70;
      const th = Math.random() * Math.PI * 2, ph = Math.acos(2 * Math.random() - 1);
      s.position.set(r * Math.sin(ph) * Math.cos(th), r * Math.cos(ph) * 0.6, r * Math.sin(ph) * Math.sin(th));
      const sc = 20 + Math.random() * 38;
      s.scale.set(sc, sc, 1);
      S.nebulaGroup.add(s);
    }
    S.scene.add(S.nebulaGroup);
  }

  // 4. Core Group (Maha Meru + Garbha Orb + Wings)
  S.coreGroup = new THREE.Group();
  S.scene.add(S.coreGroup);
  S.lineMat = new THREE.LineBasicMaterial({ color: S.current.color, transparent: true, opacity: 0.9 });

  // Maha Meru 3D Shri Yantra
  S.yantra = new THREE.Group();
  S.coreGroup.add(S.yantra);

  [[1.55, 0.0], [1.25, 0.28], [0.95, 0.56], [0.65, 0.84]].forEach(([h, z], i) => {
    const t = addLineTo(S.yantra, trianglePts(h, true));
    t.position.z = z;
    t.material = new THREE.LineBasicMaterial({ color: S.current.color, transparent: true, opacity: 0.9 - i * 0.12 });
  });
  [[1.4, 0.0], [1.1, -0.28], [0.8, -0.56], [0.5, -0.84]].forEach(([h, z], i) => {
    const t = addLineTo(S.yantra, trianglePts(h, false));
    t.position.z = z;
    t.material = new THREE.LineBasicMaterial({ color: S.current.color, transparent: true, opacity: 0.9 - i * 0.12 });
  });

  addLineTo(S.yantra, circlePts(0.18)).position.z = 1.0;
  addLineTo(S.yantra, circlePts(0.18)).position.z = -1.0;
  addLineTo(S.yantra, circlePts(1.7), true);

  function petalRing(count, innerR, outerR, tilt) {
    const g = new THREE.Group();
    for (let i = 0; i < count; i++) {
      const a = (i / count) * Math.PI * 2;
      const half = (Math.PI / count) * 0.42;
      addLineTo(g, [
        new THREE.Vector3(innerR * Math.cos(a - half), innerR * Math.sin(a - half), 0),
        new THREE.Vector3((innerR + (outerR - innerR) * 0.55) * Math.cos(a - half * 0.4), (innerR + (outerR - innerR) * 0.55) * Math.sin(a - half * 0.4), tilt),
        new THREE.Vector3(outerR * Math.cos(a), outerR * Math.sin(a), tilt * 1.6),
        new THREE.Vector3((innerR + (outerR - innerR) * 0.55) * Math.cos(a + half * 0.4), (innerR + (outerR - innerR) * 0.55) * Math.sin(a + half * 0.4), tilt),
        new THREE.Vector3(innerR * Math.cos(a + half), innerR * Math.sin(a + half), 0),
      ]);
    }
    S.yantra.add(g);
    return g;
  }
  petalRing(8, 1.78, 2.12, 0.18);
  addLineTo(S.yantra, circlePts(2.2), true);
  petalRing(16, 2.26, 2.55, 0.14);
  addLineTo(S.yantra, circlePts(2.62), true);

  // Bhupura Citadel
  S.bhupura = new THREE.Group();
  S.yantra.add(S.bhupura);
  function squareLoop(half, z) {
    return [
      new THREE.Vector3(-half, -half, z), new THREE.Vector3(half, -half, z),
      new THREE.Vector3(half, half, z), new THREE.Vector3(-half, half, z),
    ];
  }
  [[3.05, 0.12], [2.92, 0.0], [3.05, -0.12]].forEach(([half, z]) => addLineTo(S.bhupura, squareLoop(half, z), true));
  [[-3.05, -3.05], [3.05, -3.05], [3.05, 3.05], [-3.05, 3.05]].forEach(([x, y]) => {
    addLineTo(S.bhupura, [new THREE.Vector3(x, y, 0.12), new THREE.Vector3(x, y, -0.12)]);
  });
  const gateW = 1.0, gateD = 0.62;
  for (let k = 0; k < 4; k++) {
    const g = new THREE.Group();
    [[gateW, gateD, 0.1], [gateW * 0.7, gateD * 1.28, 0.0], [gateW * 0.4, gateD * 1.52, -0.1]].forEach(([w, d, z]) => {
      addLineTo(g, [
        new THREE.Vector3(-w / 2, 3.05, z), new THREE.Vector3(-w / 2, 3.05 + d, z),
        new THREE.Vector3(w / 2, 3.05 + d, z), new THREE.Vector3(w / 2, 3.05, z),
      ]);
    });
    g.rotation.z = k * Math.PI / 2;
    S.bhupura.add(g);
  }

  // Black Hole Orb & Accretion Shaders (Exact Initial Scale)
  S.orbGroup = new THREE.Group();
  S.coreGroup.add(S.orbGroup);
  S.orbGroup.add(new THREE.Mesh(
    new THREE.SphereGeometry(0.52, 48, 48),
    new THREE.MeshBasicMaterial({ color: 0x000000 })
  ));

  S.diskUniforms = {
    uTime: { value: 0 }, uSwirl: { value: S.current.swirl }, uColor: { value: new THREE.Color(S.current.color) }
  };
  const diskMat = new THREE.ShaderMaterial({
    uniforms: S.diskUniforms, transparent: true, depthWrite: false, side: THREE.DoubleSide, blending: THREE.AdditiveBlending,
    vertexShader: `varying vec2 vUv; void main(){ vUv=uv; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}`,
    fragmentShader: `
      varying vec2 vUv; uniform float uTime; uniform float uSwirl; uniform vec3 uColor;
      void main(){
        vec2 c = vUv-0.5; float dist=length(c)*2.0; float angle=atan(c.y,c.x);
        float swirl = sin(angle*6.0 - uTime*uSwirl + dist*10.0)*0.5+0.5;
        float ring = smoothstep(0.15,0.22,dist)*(1.0-smoothstep(0.55,0.9,dist));
        float facet = 0.8+0.2*cos(angle*3.0+uTime*0.15);
        float alpha = ring*(0.35+0.65*swirl)*facet;
        vec3 hot = mix(vec3(1.0), uColor, smoothstep(0.15,0.4,dist));
        gl_FragColor = vec4(hot, alpha);
      }`
  });
  const diskGeo = new THREE.PlaneGeometry(6, 6);
  const diskH = new THREE.Mesh(diskGeo, diskMat); diskH.rotation.x = Math.PI / 2; S.orbGroup.add(diskH);
  const diskV = new THREE.Mesh(diskGeo, diskMat); diskV.rotation.y = Math.PI / 2; S.orbGroup.add(diskV);

  S.glowSprite = new THREE.Sprite(new THREE.SpriteMaterial({
    map: softTex, color: S.current.color, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false
  }));
  S.glowSprite.scale.set(5.5, 5.5, 1);
  S.orbGroup.add(S.glowSprite);

  // Phoenix Wings (Exact Initial Scale)
  S.wingsGroup = new THREE.Group();
  S.coreGroup.add(S.wingsGroup);
  S.featherMats = [];
  S.wingL = buildPhoenixWing(-1);
  S.wingR = buildPhoenixWing(1);
  S.wingsGroup.add(S.wingL, S.wingR);

  // Embers
  S.emberGeo = new THREE.BufferGeometry();
  const emberPos = new Float32Array(S.emberCount * 3);
  S.emberSeed = new Float32Array(S.emberCount);
  for (let i = 0; i < S.emberCount; i++) {
    const side = i % 2 === 0 ? 1 : -1;
    emberPos[i * 3] = side * (3.5 + Math.random() * 7);
    emberPos[i * 3 + 1] = -0.5 + Math.random() * 6;
    emberPos[i * 3 + 2] = (Math.random() - 0.5) * 1.6;
    S.emberSeed[i] = Math.random() * 100;
  }
  S.emberGeo.setAttribute('position', new THREE.BufferAttribute(emberPos, 3));
  S.emberMat = new THREE.PointsMaterial({ size: 0.16, map: softTex, color: S.current.color, transparent: true, opacity: 0.8, depthWrite: false, blending: THREE.AdditiveBlending });
  const embers = new THREE.Points(S.emberGeo, S.emberMat);
  S.coreGroup.add(embers);

  // Ground Mandala Rings
  S.ringMats = [];
  [[4.8, -4.2, 0.3], [5.5, -4.35, 0.22], [6.3, -4.5, 0.15], [7.2, -4.65, 0.1]].forEach(([r, y, op]) => {
    const mat = new THREE.LineBasicMaterial({ color: S.current.color, transparent: true, opacity: op });
    S.ringMats.push(mat);
    const ring = addLineTo(S.coreGroup, circlePts(r, 90), true, mat);
    ring.rotation.x = Math.PI / 2; ring.position.y = y;
  });
  {
    const mat = new THREE.LineBasicMaterial({ color: S.current.color, transparent: true, opacity: 0.12 });
    S.ringMats.push(mat);
    for (let i = 0; i < 24; i++) {
      const a = (i / 24) * Math.PI * 2;
      addLineTo(S.coreGroup, [
        new THREE.Vector3(Math.cos(a) * 4.8, -4.2, Math.sin(a) * 4.8),
        new THREE.Vector3(Math.cos(a) * 7.2, -4.65, Math.sin(a) * 7.2),
      ], false, mat);
    }
  }
}

function bindCameraEvents(dom) {
  dom.addEventListener('pointerdown', e => { S.dragging = true; S.lastX = e.clientX; S.lastY = e.clientY; });
  window.addEventListener('pointerup', () => S.dragging = false);
  window.addEventListener('pointermove', e => {
    if (!S.dragging) return;
    S.camTheta -= (e.clientX - S.lastX) * 0.005;
    S.camPhi = Math.min(Math.max(S.camPhi - (e.clientY - S.lastY) * 0.005, 0.25), Math.PI - 0.25);
    S.lastX = e.clientX; S.lastY = e.clientY;
  });
  window.addEventListener('wheel', e => {
    S.camRadius = Math.min(Math.max(S.camRadius + e.deltaY * 0.02, 9), 60);
  }, { passive: true });
}

function frame() {
  if (!S.running) return;
  const el = S.clock.getElapsedTime();

  S.current.color.lerp(new THREE.Color(S.target.color), 0.04);
  S.current.rot   += (S.target.rot   - S.current.rot) * 0.05;
  S.current.swirl += (S.target.swirl - S.current.swirl) * 0.05;
  S.current.wing  += (S.target.wing  - S.current.wing) * 0.05;
  S.current.flap  += (S.target.flap  - S.current.flap) * 0.05;

  let audioBoost = 0;
  if (typeof S.getAudioLevel === "function") {
    const lvl = S.getAudioLevel();
    if (typeof lvl === "number" && !isNaN(lvl)) audioBoost = lvl;
  }

  S.lineMat.color.copy(S.current.color);
  if (S.yantra) S.yantra.traverse(o => { if (o.material && o.material.isLineBasicMaterial) o.material.color.copy(S.current.color); });
  if (S.bhupura) S.bhupura.traverse(o => { if (o.material) o.material.color.copy(S.current.color); });
  S.ringMats.forEach(m => m.color.copy(S.current.color));
  if (S.emberMat) S.emberMat.color.copy(S.current.color);
  if (S.glowSprite) S.glowSprite.material.color.copy(S.current.color);
  if (S.coreLight) S.coreLight.color.copy(S.current.color);
  S.featherMats.forEach(({ mat, heat }) => { mat.emissive.copy(S.current.color); mat.emissiveIntensity = heat * (0.85 + 0.15 * Math.sin(el * 3)); });
  if (S.wingsGroup) S.wingsGroup.traverse(o => { if (o.material && o.material.isLineBasicMaterial) o.material.color.copy(S.current.color); });

  if (S.diskUniforms) {
    S.diskUniforms.uTime.value = el * 1.0;
    S.diskUniforms.uSwirl.value = S.current.swirl + audioBoost * 2.0;
    S.diskUniforms.uColor.value.copy(S.current.color);
  }

  // Smooth Normal Rotation Speed
  if (S.coreGroup) S.coreGroup.rotation.y += S.current.rot;
  if (S.orbGroup) {
    S.orbGroup.rotation.y += S.current.rot * 1.6;
    S.orbGroup.rotation.z += S.current.rot * 0.8;
    const pulse = S.target.pulse ? 1 + 0.06 * Math.sin(el * 8) + audioBoost * 0.2 : 1 + audioBoost * 0.12;
    S.orbGroup.scale.setScalar(pulse);
  }
  if (S.coreLight) S.coreLight.intensity = 2.2 + Math.sin(el * 3.2) * 0.7 + (S.target.pulse ? Math.sin(el * 8) * 0.8 : 0) + audioBoost * 2.5;

  if (S.yantra) S.yantra.scale.setScalar(1 + 0.02 * Math.sin(el * 1.2));

  const beat = Math.sin(el * 2.0) * 0.1 * S.current.flap;
  if (S.wingL) S.wingL.rotation.z = beat;
  if (S.wingR) S.wingR.rotation.z = -beat;
  [S.wingL, S.wingR].forEach(w => {
    if (w) w.children.forEach(f => {
      if (!f.isMesh || f.userData.baseRotZ === undefined) return;
      const ripple = Math.sin(el * 3.2 - f.userData.t * 2.8) * 0.08 * S.current.flap;
      f.rotation.z = f.userData.baseRotZ + f.userData.side * ripple;
    });
  });
  if (S.wingsGroup) S.wingsGroup.scale.setScalar(S.current.wing);

  if (S.emberGeo) {
    const pa = S.emberGeo.attributes.position.array;
    for (let i = 0; i < S.emberCount; i++) {
      pa[i * 3 + 1] += 0.012 + 0.006 * Math.sin(S.emberSeed[i]);
      pa[i * 3]     += Math.sin(el * 2.0 + S.emberSeed[i]) * 0.004;
      if (pa[i * 3 + 1] > 9) { pa[i * 3 + 1] = -0.5 + Math.random() * 2.5; }
    }
    S.emberGeo.attributes.position.needsUpdate = true;
  }
  if (S.emberMat) S.emberMat.opacity = 0.55 + 0.35 * Math.sin(el * 4);

  if (S.galaxy) S.galaxy.rotation.z += 0.0008;
  if (S.nebulaGroup) S.nebulaGroup.rotation.y += 0.00025;

  if (!S.dragging) S.camTheta += 0.0018;
  if (S.camera) {
    S.camera.position.set(
      S.camRadius * Math.sin(S.camPhi) * Math.sin(S.camTheta),
      S.camRadius * Math.cos(S.camPhi),
      S.camRadius * Math.sin(S.camPhi) * Math.cos(S.camTheta)
    );
    S.camera.lookAt(0, 0.5, 0);
  }

  if (S.renderer && S.scene && S.camera) {
    S.renderer.render(S.scene, S.camera);
  }

  S.rafId = requestAnimationFrame(frame);
}

function onResize() {
  if (!S.container || !S.renderer || !S.camera) return;
  const w = window.innerWidth;
  const h = window.innerHeight;
  if (w === 0 || h === 0) return;

  S.camera.aspect = w / h;
  S.camera.updateProjectionMatrix();
  S.renderer.setSize(w, h);
}

const Battleground = {
  async init({ container, getAudioLevel }) {
    if (S.inited && S.container === container) return;
    S.container = container;
    S.getAudioLevel = getAudioLevel;
    S.clock = new THREE.Clock();

    S.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    S.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    S.renderer.setSize(window.innerWidth, window.innerHeight);
    container.appendChild(S.renderer.domElement);

    buildScene();
    bindCameraEvents(S.renderer.domElement);

    S.resizeObserver = new ResizeObserver(onResize);
    S.resizeObserver.observe(document.body);
    onResize();

    S.inited = true;
  },

  setState(name) {
    const key = String(name || 'idle').toLowerCase();
    if (!STATES[key]) return;
    S.stateName = key;
    S.target = STATES[key];
  },

  setClusterHealth(map) {
    Object.assign(S.clusterHealth, map);
  },

  resume() {
    if (S.running) return;
    S.running = true;
    S.clock.start();
    S.rafId = requestAnimationFrame(frame);
  },

  pause() {
    S.running = false;
    if (S.clock) S.clock.stop();
    cancelAnimationFrame(S.rafId);
  },

  dispose() {
    this.pause();
    if (S.resizeObserver) S.resizeObserver.disconnect();
    if (S.renderer) {
      S.renderer.dispose();
      if (S.renderer.domElement) S.renderer.domElement.remove();
    }
    S.inited = false;
  },
};

export default Battleground;
