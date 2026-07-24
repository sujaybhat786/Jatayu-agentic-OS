/**
 * ════════════════════════════════════════════════════════════════
 * JATAYU OS — battleground_scene.js
 * Isolated 3D Shri Yantra Core & GLSL Black Hole Renderer Engine
 * 
 * Scene Hierarchy:
 * - Outer Tesseract / Wireframe Cube
 * - Nine-Triangle Shri Yantra (Shiva & Shakti interlocking layers)
 * - Black Hole Orb:
 *   - Accretion Disk (GLSL noise spiral & Doppler beaming)
 *   - Event Horizon (Opaque body + Fresnel rim)
 *   - Photon Ring (Camera-facing lensing halo)
 *   - Infall Particles (GPU spiral drift)
 * - 4 Feathered Wings (Google Workspace, Comms, Knowledge, Voice)
 * - Concentric Ground Dais & Horizontal Dust Streams
 * - Volumetric Back-glow Haze
 * 
 * State Engine:
 * - IDLE: Guardian Gold (resting identity)
 * - LISTENING: Ice Blue (active user input)
 * - THINKING: Bright Gold (cognitive pulse)
 * - SPEAKING: Pearl White (vocal output)
 * - ALERT: Crimson (error / safety event)
 * ════════════════════════════════════════════════════════════════
 */

import * as THREE from "three";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";

/* ---------- Color Palettes ---------- */
const PAL = {
  ice:     { line: new THREE.Color(0xa9d6ff), hi: new THREE.Color(0xeaf4ff), lo: new THREE.Color(0x4c7fa6) },
  gold:    { line: new THREE.Color(0xe8b84b), hi: new THREE.Color(0xffe9b0), lo: new THREE.Color(0x8a652a) },
  pearl:   { line: new THREE.Color(0xede6d6), hi: new THREE.Color(0xffffff), lo: new THREE.Color(0x8f887a) },
  crimson: { line: new THREE.Color(0xe14b4b), hi: new THREE.Color(0xff8080), lo: new THREE.Color(0x6e1e1e) },
  chrome:  { line: new THREE.Color(0x6b7280), hi: new THREE.Color(0x9ca3af), lo: new THREE.Color(0x374151) },
};

const VOID = 0x05060a;

/* ---------- Per-State Animation Targets ---------- */
const STATES = {
  IDLE:      { pal: "gold",    activity: 0.2,  bloom: 0.7,  flare: 0.0,   motion: 0.5,  rim: 1.0 },
  LISTENING: { pal: "ice",     activity: 0.45, bloom: 0.85, flare: 1.0,   motion: 0.55, rim: 1.9 },
  THINKING:  { pal: "gold",    activity: 0.9,  bloom: 1.05, flare: 0.35,  motion: 0.85, rim: 1.25 },
  SPEAKING:  { pal: "pearl",   activity: 0.7,  bloom: 0.9,  flare: 0.55,  motion: 0.6,  rim: 1.4 },
  ALERT:     { pal: "crimson", activity: 0.05, bloom: 0.65, flare: -0.55, motion: 0.04, rim: 1.5 },
};

/* ---------- Scale Definitions ---------- */
const CUBE_HALF = 1.9;
const YANTRA_R = 1.15;
const ORB_R = 0.42;
const DISK_INNER = 0.6;
const DISK_OUTER = 1.62;
const PARTICLE_COUNT = 1400;

/* ════════════════════════════════════════════════════
   GLSL SHADERS
   ════════════════════════════════════════════════════ */

const DISK_VERT = /* glsl */ `
  varying vec2 vPos;
  void main() {
    vPos = position.xy;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

const DISK_FRAG = /* glsl */ `
  precision highp float;
  varying vec2 vPos;
  uniform float uTime;
  uniform float uActivity;
  uniform float uPulse;
  uniform vec3 uColor;
  uniform vec3 uHi;
  uniform float uInner;
  uniform float uOuter;

  float hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
  }
  float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(
      mix(hash(i), hash(i + vec2(1.0, 0.0)), u.x),
      mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), u.x),
      u.y
    );
  }
  float fbm(vec2 p) {
    float v = 0.0;
    float a = 0.5;
    for (int i = 0; i < 4; i++) {
      v += a * noise(p);
      p = p * 2.13 + vec2(11.7, 5.3);
      a *= 0.5;
    }
    return v;
  }

  void main() {
    float r = length(vPos);
    if (r > uOuter || r < uInner * 0.72) discard;

    float theta = atan(vPos.y, vPos.x);
    float speed = (0.35 + 1.75 * uActivity) / max(r, 0.35);
    float swirl = theta * 3.0 + r * 6.5 - uTime * speed;

    float streaks = fbm(vec2(swirl, r * 9.0));
    streaks = pow(streaks, 1.55);

    float heat = pow(smoothstep(uOuter, uInner, r), 1.25);
    float edgeIn = smoothstep(uInner * 0.72, uInner, r);
    float edgeOut = smoothstep(uOuter, uOuter - 0.25, r);

    float beam = 1.0 + 0.65 * sin(theta + uTime * 0.07);

    float a = streaks * heat * edgeIn * edgeOut * beam;
    a *= (1.5 + 0.9 * uActivity) * (1.0 + 0.7 * uPulse);

    vec3 col = mix(uColor, uHi, clamp(heat * streaks * 1.6, 0.0, 1.0));
    gl_FragColor = vec4(col * a, a);
  }
`;

const HORIZON_VERT = /* glsl */ `
  varying vec3 vN;
  varying vec3 vV;
  void main() {
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    vN = normalMatrix * normal;
    vV = -mv.xyz;
    gl_Position = projectionMatrix * mv;
  }
`;

const HORIZON_FRAG = /* glsl */ `
  precision highp float;
  varying vec3 vN;
  varying vec3 vV;
  uniform vec3 uColor;
  uniform vec3 uHi;
  uniform float uRim;
  void main() {
    float fres = pow(1.0 - abs(dot(normalize(vN), normalize(vV))), 4.5);
    vec3 col = mix(uColor, uHi, 0.5) * fres * uRim;
    gl_FragColor = vec4(col, 1.0);
  }
`;

const RING_FRAG = /* glsl */ `
  precision highp float;
  varying vec2 vPos;
  uniform vec3 uColor;
  uniform vec3 uHi;
  uniform float uRadius;
  uniform float uWidth;
  uniform float uIntensity;
  void main() {
    float d = length(vPos);
    float ring = exp(-pow((d - uRadius) / uWidth, 2.0));
    float halo = 0.1 * exp(-pow((d - uRadius) / (uWidth * 5.0), 2.0));
    float a = (ring + halo) * uIntensity;
    gl_FragColor = vec4(mix(uColor, uHi, 0.65) * a, a);
  }
`;

const PARTICLE_VERT = /* glsl */ `
  attribute float aSeed;
  attribute float aTilt;
  varying float vFade;
  varying float vMix;
  uniform float uTime;
  uniform float uActivity;
  uniform float uRmin;
  uniform float uRmax;
  uniform float uSize;
  void main() {
    float speed = 0.015 + 0.14 * fract(aSeed * 7.31);
    float t = fract(aSeed + uTime * speed * (0.12 + uActivity));
    float r = mix(uRmax, uRmin, t * t);
    float ang = aSeed * 251.327 + uTime * (0.08 + 0.55 * uActivity) / max(r, 0.4) + t * 7.0;
    vec3 p = vec3(cos(ang) * r, aTilt * 0.16 * (r / uRmax), sin(ang) * r);

    vFade = smoothstep(uRmin, uRmin + 0.3, r) * smoothstep(uRmax, uRmax - 0.35, r);
    vMix = t;

    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_PointSize = uSize * (0.6 + fract(aSeed * 3.7)) * (140.0 / -mv.z);
    gl_Position = projectionMatrix * mv;
  }
`;

const PARTICLE_FRAG = /* glsl */ `
  precision highp float;
  varying float vFade;
  varying float vMix;
  uniform vec3 uColor;
  uniform vec3 uHi;
  uniform float uActivity;
  void main() {
    vec2 c = gl_PointCoord - 0.5;
    float a = smoothstep(0.5, 0.0, length(c));
    a = a * a * vFade * (0.12 + 0.55 * uActivity);
    vec3 col = mix(uColor, uHi, vMix * 0.75);
    gl_FragColor = vec4(col * a, a);
  }
`;

const DUST_VERT = /* glsl */ `
  attribute float aSeed;
  varying float vA;
  uniform float uTime;
  uniform float uSize;
  void main() {
    float s1 = fract(aSeed * 13.73);
    float s2 = fract(aSeed * 57.31);
    float side = s1 < 0.5 ? -1.0 : 1.0;
    float t = fract(aSeed + uTime * (0.006 + 0.012 * s2));
    float x = side * (2.3 + t * 5.6);
    float y = (s2 - 0.5) * 2.4 * (0.35 + t) + sin(t * 11.0 + aSeed * 43.0) * 0.14;
    float z = (fract(aSeed * 7.91) - 0.5) * 3.2;
    vA = smoothstep(0.0, 0.15, t) * (1.0 - smoothstep(0.7, 1.0, t));
    vec4 mv = modelViewMatrix * vec4(x, y, z, 1.0);
    gl_PointSize = uSize * (0.5 + s2) * (140.0 / -mv.z);
    gl_Position = projectionMatrix * mv;
  }
`;

const DUST_FRAG = /* glsl */ `
  precision highp float;
  varying float vA;
  uniform vec3 uColor;
  uniform vec3 uHi;
  void main() {
    vec2 c = gl_PointCoord - 0.5;
    float a = smoothstep(0.5, 0.0, length(c));
    a = a * a * vA * 0.45;
    gl_FragColor = vec4(mix(uColor, uHi, 0.3) * a, a);
  }
`;

const GLOW_FRAG = /* glsl */ `
  precision highp float;
  varying vec2 vPos;
  uniform vec3 uColor;
  uniform float uIntensity;
  void main() {
    float d = length(vPos) / 4.0;
    float a = exp(-d * d * 3.2) * uIntensity;
    gl_FragColor = vec4(uColor * a, a);
  }
`;

/* ════════════════════════════════════════════════════
   ENGINE INTERNAL STATE
   ════════════════════════════════════════════════════ */

const S = {
  inited: false,
  webgl: true,
  reducedMotion: false,
  running: false,
  rafId: 0,

  container: null,
  getAudioLevel: null,

  renderer: null,
  composer: null,
  bloomPass: null,
  scene: null,
  camera: null,
  resizeObserver: null,

  coreGroup: null,
  cubeGroup: null,
  yantra: null,
  orbGroup: null,
  diskGroup: null,
  ringMesh: null,
  wingL: null,
  wingR: null,
  particles: null,
  dais: null,
  dust: null,
  glowMesh: null,

  stateLineMats: [],
  wingMats: { google: [], comms: [], knowledge: [], voice: [] },
  clusterHealth: { google: "healthy", comms: "healthy", knowledge: "healthy", voice: "healthy" },

  diskUniforms: null,
  horizonUniforms: null,
  ringUniforms: null,
  particleUniforms: null,
  dustUniforms: null,
  glowUniforms: null,

  stateName: "IDLE",
  target: { ...STATES.IDLE },
  cur: {
    line: PAL.ice.line.clone(),
    hi: PAL.ice.hi.clone(),
    activity: 0.22,
    bloom: 0.95,
    flare: 0,
    motion: 1,
    rim: 1,
  },
  pulse: 0,
  shaderTime: 0,
  lastTime: 0,
  baseScale: 1,

  perfLevel: 0,
  frameAcc: 0,
  frameCount: 0,

  fallbackEl: null,
};

const _tmpColor = new THREE.Color();

/* ════════════════════════════════════════════════════
   GEOMETRY HELPER FUNCTIONS
   ════════════════════════════════════════════════════ */

function makeLineMat(k) {
  const m = new THREE.LineBasicMaterial({
    transparent: true,
    opacity: 0.95,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });
  S.stateLineMats.push({ m, k });
  return m;
}

function makeWingMat(clusterId, k) {
  const m = new THREE.LineBasicMaterial({
    transparent: true,
    opacity: 0.95,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });
  S.wingMats[clusterId].push({ m, k });
  return m;
}

function loopFromPoints(pts, mat) {
  const g = new THREE.BufferGeometry().setFromPoints(pts);
  return new THREE.LineLoop(g, mat);
}

function segmentsFromPoints(pts, mat) {
  const g = new THREE.BufferGeometry().setFromPoints(pts);
  return new THREE.LineSegments(g, mat);
}

function circlePoints(r, n) {
  const pts = [];
  for (let i = 0; i < n; i++) {
    const a = (i / n) * Math.PI * 2;
    pts.push(new THREE.Vector3(Math.cos(a) * r, Math.sin(a) * r, 0));
  }
  return pts;
}

function squarePoints(half) {
  return [
    new THREE.Vector3(-half, -half, 0),
    new THREE.Vector3(half, -half, 0),
    new THREE.Vector3(half, half, 0),
    new THREE.Vector3(-half, half, 0),
  ];
}

function trianglePoints(r, pointsUp) {
  const start = pointsUp ? Math.PI / 2 : -Math.PI / 2;
  const pts = [];
  for (let i = 0; i < 3; i++) {
    const a = start + (i / 3) * Math.PI * 2;
    pts.push(new THREE.Vector3(Math.cos(a) * r, Math.sin(a) * r, 0));
  }
  return pts;
}

function petalPoints(rIn, rOut, count) {
  const pts = [];
  const steps = 8;
  for (let i = 0; i < count; i++) {
    const a0 = (i / count) * Math.PI * 2;
    const a1 = ((i + 1) / count) * Math.PI * 2;
    let prev = null;
    for (let s = 0; s <= steps; s++) {
      const t = s / steps;
      const ang = a0 + (a1 - a0) * t;
      const r = rIn + (rOut - rIn) * Math.sin(Math.PI * t);
      const p = new THREE.Vector3(Math.cos(ang) * r, Math.sin(ang) * r, 0);
      if (prev) pts.push(prev, p);
      prev = p;
    }
  }
  return pts;
}

/* ════════════════════════════════════════════════════
   SCENE BUILDERS
   ════════════════════════════════════════════════════ */

function buildYantra() {
  const group = new THREE.Group();
  const mat = makeLineMat(0.72);

  const frame = new THREE.Group();
  frame.add(loopFromPoints(squarePoints(YANTRA_R * 1.28), makeLineMat(0.4)));
  frame.add(loopFromPoints(squarePoints(YANTRA_R * 1.2), makeLineMat(0.3)));
  for (const r of [1.0, 0.94, 0.88]) {
    frame.add(loopFromPoints(circlePoints(YANTRA_R * r, 96), mat));
  }
  frame.add(segmentsFromPoints(petalPoints(YANTRA_R * 1.0, YANTRA_R * 1.14, 16), makeLineMat(0.45)));
  frame.position.z = -0.14;

  const down = new THREE.Group();
  for (const r of [0.86, 0.72, 0.57, 0.42, 0.27]) {
    down.add(loopFromPoints(trianglePoints(YANTRA_R * r, false), mat));
  }
  down.position.z = 0;

  const up = new THREE.Group();
  for (const r of [0.79, 0.64, 0.49, 0.34]) {
    up.add(loopFromPoints(trianglePoints(YANTRA_R * r, true), mat));
  }
  up.position.z = 0.14;

  group.add(frame, down, up);
  return { group, frame, down, up };
}

function buildCube() {
  const group = new THREE.Group();
  const h = CUBE_HALF;
  const outerMat = makeLineMat(0.85);

  const corners = [
    new THREE.Vector3(-h,-h,-h), new THREE.Vector3( h,-h,-h),
    new THREE.Vector3( h, h,-h), new THREE.Vector3(-h, h,-h),
    new THREE.Vector3(-h,-h, h), new THREE.Vector3( h,-h, h),
    new THREE.Vector3( h, h, h), new THREE.Vector3(-h, h, h),
  ];
  const edges = [
    0,1, 1,2, 2,3, 3,0,
    4,5, 5,6, 6,7, 7,4,
    0,4, 1,5, 2,6, 3,7,
  ];
  const pts = [];
  for (let i = 0; i < edges.length; i += 2) {
    pts.push(corners[edges[i]], corners[edges[i + 1]]);
  }
  group.add(segmentsFromPoints(pts, outerMat));

  const innerMat = makeLineMat(0.42);
  const ih = h * 0.65;
  const icorners = [
    new THREE.Vector3(-ih,-ih,-ih), new THREE.Vector3( ih,-ih,-ih),
    new THREE.Vector3( ih, ih,-ih), new THREE.Vector3(-ih, ih,-ih),
    new THREE.Vector3(-ih,-ih, ih), new THREE.Vector3( ih,-ih, ih),
    new THREE.Vector3( ih, ih, ih), new THREE.Vector3(-ih, ih, ih),
  ];
  const ipts = [];
  for (let i = 0; i < edges.length; i += 2) {
    ipts.push(icorners[edges[i]], icorners[edges[i + 1]]);
  }
  for (let i = 0; i < 8; i++) {
    ipts.push(corners[i], icorners[i]);
  }
  group.add(segmentsFromPoints(ipts, innerMat));

  return group;
}

function buildOrb() {
  const group = new THREE.Group();

  S.diskUniforms = {
    uTime:     { value: 0 },
    uActivity: { value: 0.2 },
    uPulse:    { value: 0 },
    uColor:    { value: PAL.gold.line },
    uHi:       { value: PAL.gold.hi },
    uInner:    { value: DISK_INNER },
    uOuter:    { value: DISK_OUTER },
  };
  const diskGeo = new THREE.PlaneGeometry(DISK_OUTER * 2, DISK_OUTER * 2);
  const diskMat = new THREE.ShaderMaterial({
    vertexShader: DISK_VERT,
    fragmentShader: DISK_FRAG,
    uniforms: S.diskUniforms,
    transparent: true,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
    side: THREE.DoubleSide,
  });
  const diskMesh = new THREE.Mesh(diskGeo, diskMat);
  diskMesh.rotation.x = Math.PI * 0.42;

  S.diskGroup = new THREE.Group();
  S.diskGroup.add(diskMesh);
  group.add(S.diskGroup);

  S.horizonUniforms = {
    uColor: { value: PAL.gold.line },
    uHi:    { value: PAL.gold.hi },
    uRim:   { value: 1.0 },
  };
  const horizGeo = new THREE.SphereGeometry(ORB_R, 48, 48);
  const horizMat = new THREE.ShaderMaterial({
    vertexShader: HORIZON_VERT,
    fragmentShader: HORIZON_FRAG,
    uniforms: S.horizonUniforms,
  });
  const horizMesh = new THREE.Mesh(horizGeo, horizMat);
  group.add(horizMesh);

  S.ringUniforms = {
    uColor:     { value: PAL.gold.line },
    uHi:        { value: PAL.gold.hi },
    uRadius:    { value: ORB_R * 1.06 },
    uWidth:     { value: 0.04 },
    uIntensity: { value: 1.2 },
  };
  const ringGeo = new THREE.PlaneGeometry(ORB_R * 2.8, ORB_R * 2.8);
  const ringMat = new THREE.ShaderMaterial({
    vertexShader: DISK_VERT,
    fragmentShader: RING_FRAG,
    uniforms: S.ringUniforms,
    transparent: true,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });
  S.ringMesh = new THREE.Mesh(ringGeo, ringMat);
  group.add(S.ringMesh);

  return group;
}

function buildParticles() {
  const geo = new THREE.BufferGeometry();
  const seeds = new Float32Array(PARTICLE_COUNT);
  const tilts = new Float32Array(PARTICLE_COUNT);
  const pos   = new Float32Array(PARTICLE_COUNT * 3);

  for (let i = 0; i < PARTICLE_COUNT; i++) {
    seeds[i] = Math.random();
    tilts[i] = (Math.random() - 0.5) * 2.0;
  }
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  geo.setAttribute("aSeed", new THREE.BufferAttribute(seeds, 1));
  geo.setAttribute("aTilt", new THREE.BufferAttribute(tilts, 1));

  S.particleUniforms = {
    uTime:     { value: 0 },
    uActivity: { value: 0.2 },
    uRmin:     { value: ORB_R * 0.8 },
    uRmax:     { value: DISK_OUTER * 1.1 },
    uSize:     { value: 2.2 },
    uColor:    { value: PAL.gold.line },
    uHi:       { value: PAL.gold.hi },
  };

  const mat = new THREE.ShaderMaterial({
    vertexShader: PARTICLE_VERT,
    fragmentShader: PARTICLE_FRAG,
    uniforms: S.particleUniforms,
    transparent: true,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });

  return new THREE.Points(geo, mat);
}

function buildWing(clusterId, flip) {
  const group = new THREE.Group();
  const sign = flip ? -1 : 1;

  const featherCount = 14;
  for (let i = 0; i < featherCount; i++) {
    const t = i / (featherCount - 1);
    const k = 0.35 + 0.6 * (1 - t);
    const mat = makeWingMat(clusterId, k);

    const length = 1.35 + 1.95 * Math.sin(Math.PI * (0.15 + 0.75 * t));
    const arch   = 0.25 + 0.85 * Math.pow(t, 1.3);
    const curve  = (0.1 + 0.35 * t) * sign;

    const steps = 18;
    const pts = [];
    let prev = null;
    for (let s = 0; s <= steps; s++) {
      const u = s / steps;
      const x = sign * (CUBE_HALF * 0.95 + u * length * (0.85 + 0.15 * t));
      const y = arch * Math.sin(Math.PI * u * 0.85) - u * u * 0.3;
      const z = curve * Math.sin(Math.PI * u);

      const p = new THREE.Vector3(x, y, z);
      if (prev) pts.push(prev, p);
      prev = p;
    }
    group.add(segmentsFromPoints(pts, mat));
  }

  const spineMat = makeWingMat(clusterId, 0.95);
  const spinePts = [];
  let prevSpine = null;
  for (let i = 0; i <= 24; i++) {
    const t = i / 24;
    const x = sign * (CUBE_HALF * 0.9 + t * 2.8);
    const y = (0.2 + 0.9 * Math.pow(t, 1.2)) * Math.sin(Math.PI * t * 0.7);
    const z = sign * 0.25 * Math.sin(Math.PI * t);
    const p = new THREE.Vector3(x, y, z);
    if (prevSpine) spinePts.push(prevSpine, p);
    prevSpine = p;
  }
  group.add(segmentsFromPoints(spinePts, spineMat));

  return group;
}

function buildWings() {
  const group = new THREE.Group();

  const googleL = buildWing("google", false);
  const googleR = buildWing("google", true);

  const commsL = buildWing("comms", false);
  const commsR = buildWing("comms", true);
  commsL.position.y = -0.35; commsR.position.y = -0.35;
  commsL.rotation.z = -0.12; commsR.rotation.z = 0.12;

  const knowL = buildWing("knowledge", false);
  const knowR = buildWing("knowledge", true);
  knowL.position.y = 0.35; knowR.position.y = 0.35;
  knowL.rotation.z = 0.12; knowR.rotation.z = -0.12;

  const voiceL = buildWing("voice", false);
  const voiceR = buildWing("voice", true);
  voiceL.position.z = -0.4; voiceR.position.z = -0.4;

  group.add(googleL, googleR, commsL, commsR, knowL, knowR, voiceL, voiceR);
  S.wingL = [googleL, commsL, knowL, voiceL];
  S.wingR = [googleR, commsR, knowR, voiceR];

  return group;
}

function buildDais() {
  const group = new THREE.Group();
  group.position.y = -CUBE_HALF * 1.35;
  group.rotation.x = Math.PI * 0.46;

  const mainMat = makeLineMat(0.55);
  for (const r of [2.4, 3.1, 3.8, 4.6]) {
    group.add(loopFromPoints(circlePoints(r, 96), mainMat));
  }
  group.add(loopFromPoints(squarePoints(3.4), makeLineMat(0.35)));

  const ticks = [];
  const rIn = 4.6;
  const rOut = 4.75;
  for (let i = 0; i < 72; i++) {
    const a = (i / 72) * Math.PI * 2;
    ticks.push(
      new THREE.Vector3(Math.cos(a) * rIn, Math.sin(a) * rIn, 0),
      new THREE.Vector3(Math.cos(a) * rOut, Math.sin(a) * rOut, 0)
    );
  }
  group.add(segmentsFromPoints(ticks, makeLineMat(0.3)));
  return group;
}

function buildDust() {
  const geo = new THREE.BufferGeometry();
  const count = 450;
  const seeds = new Float32Array(count);
  const pos   = new Float32Array(count * 3);
  for (let i = 0; i < count; i++) seeds[i] = Math.random();

  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  geo.setAttribute("aSeed", new THREE.BufferAttribute(seeds, 1));

  S.dustUniforms = {
    uTime:  { value: 0 },
    uSize:  { value: 2.6 },
    uColor: { value: PAL.gold.line },
    uHi:    { value: PAL.gold.hi },
  };

  const mat = new THREE.ShaderMaterial({
    vertexShader: DUST_VERT,
    fragmentShader: DUST_FRAG,
    uniforms: S.dustUniforms,
    transparent: true,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });

  return new THREE.Points(geo, mat);
}

function buildGlow() {
  const geo = new THREE.PlaneGeometry(9.0, 9.0);
  S.glowUniforms = {
    uColor:     { value: PAL.gold.line },
    uIntensity: { value: 0.32 },
  };
  const mat = new THREE.ShaderMaterial({
    vertexShader: DISK_VERT,
    fragmentShader: GLOW_FRAG,
    uniforms: S.glowUniforms,
    transparent: true,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });
  const mesh = new THREE.Mesh(geo, mat);
  mesh.position.z = -2.2;
  return mesh;
}

function buildScene() {
  S.scene = new THREE.Scene();
  S.scene.matrixWorldAutoUpdate = true;

  S.camera = new THREE.PerspectiveCamera(40, 1, 0.1, 100);
  S.camera.position.set(0, 0.2, 8.4);

  S.coreGroup = new THREE.Group();
  S.scene.add(S.coreGroup);

  S.glowMesh = buildGlow();
  S.coreGroup.add(S.glowMesh);

  S.dais = buildDais();
  S.coreGroup.add(S.dais);

  S.dust = buildDust();
  S.coreGroup.add(S.dust);

  S.cubeGroup = buildCube();
  S.coreGroup.add(S.cubeGroup);

  S.yantra = buildYantra();
  S.coreGroup.add(S.yantra.group);

  const wings = buildWings();
  S.coreGroup.add(wings);

  S.particles = buildParticles();
  S.coreGroup.add(S.particles);

  S.orbGroup = buildOrb();
  S.coreGroup.add(S.orbGroup);
}

/* ════════════════════════════════════════════════════
   ANIMATION & RENDER LOOP
   ════════════════════════════════════════════════════ */

function updateMaterials() {
  const c = S.cur;

  for (const { m, k } of S.stateLineMats) {
    m.color.copy(c.line);
    m.opacity = 0.3 + 0.65 * k * (0.6 + 0.4 * (1 - Math.exp(-c.activity * 3)));
  }

  const clusters = ["google", "comms", "knowledge", "voice"];
  for (const cid of clusters) {
    const health = S.clusterHealth[cid] || "healthy";
    let baseColor = c.line;
    if (health === "degraded") baseColor = PAL.chrome.line;
    else if (health === "failed") baseColor = PAL.crimson.line;

    for (const { m, k } of S.wingMats[cid]) {
      m.color.copy(baseColor);
      m.opacity = 0.25 + 0.7 * k;
    }
  }

  if (S.diskUniforms) {
    S.diskUniforms.uColor.value.copy(c.line);
    S.diskUniforms.uHi.value.copy(c.hi);
    S.diskUniforms.uActivity.value = c.activity;
    S.diskUniforms.uPulse.value = S.pulse;
  }
  if (S.horizonUniforms) {
    S.horizonUniforms.uColor.value.copy(c.line);
    S.horizonUniforms.uHi.value.copy(c.hi);
    S.horizonUniforms.uRim.value = c.rim;
  }
  if (S.ringUniforms) {
    S.ringUniforms.uColor.value.copy(c.line);
    S.ringUniforms.uHi.value.copy(c.hi);
    S.ringUniforms.uIntensity.value = 0.7 + 0.8 * c.rim;
  }
  if (S.particleUniforms) {
    S.particleUniforms.uColor.value.copy(c.line);
    S.particleUniforms.uHi.value.copy(c.hi);
    S.particleUniforms.uActivity.value = c.activity;
  }
  if (S.dustUniforms) {
    S.dustUniforms.uColor.value.copy(c.line);
    S.dustUniforms.uHi.value.copy(c.hi);
  }
  if (S.glowUniforms) {
    S.glowUniforms.uColor.value.copy(c.line);
    S.glowUniforms.uIntensity.value = 0.2 + 0.3 * c.activity;
  }
  if (S.bloomPass) {
    S.bloomPass.strength = c.bloom;
  }
}

function step(dt) {
  const tgt = STATES[S.stateName] || STATES.IDLE;
  const pal = PAL[tgt.pal] || PAL.gold;
  const ease = 1 - Math.exp(-dt * 3.5);

  const c = S.cur;
  c.line.lerp(pal.line, ease);
  c.hi.lerp(pal.hi, ease);
  c.activity += (tgt.activity - c.activity) * ease;
  c.bloom    += (tgt.bloom    - c.bloom)    * ease;
  c.flare    += (tgt.flare    - c.flare)    * ease;
  c.motion   += (tgt.motion   - c.motion)   * ease;
  c.rim      += (tgt.rim      - c.rim)      * ease;

  let audioLevel = 0;
  if (S.getAudioLevel) {
    try { audioLevel = Math.min(Math.max(S.getAudioLevel(), 0), 1); } catch { /* pass */ }
  }

  S.pulse += (audioLevel * 1.35 - S.pulse) * Math.min(dt * 18, 1);
  S.pulse *= 0.94;

  S.shaderTime += dt * (0.65 + 0.85 * c.motion);

  if (S.diskUniforms) S.diskUniforms.uTime.value = S.shaderTime;
  if (S.particleUniforms) S.particleUniforms.uTime.value = S.shaderTime;
  if (S.dustUniforms) S.dustUniforms.uTime.value = S.shaderTime;

  const t = S.shaderTime;
  const m = c.motion;

  if (S.cubeGroup) {
    S.cubeGroup.rotation.y = t * 0.12 * m;
    S.cubeGroup.rotation.x = Math.sin(t * 0.09) * 0.14 * m;
    S.cubeGroup.rotation.z = Math.cos(t * 0.07) * 0.08 * m;
  }

  if (S.yantra) {
    S.yantra.frame.rotation.z = t * 0.03 * m;
    S.yantra.down.rotation.z  = -t * 0.08 * m;
    S.yantra.up.rotation.z    = t * 0.11 * m;
  }

  if (S.diskGroup) {
    S.diskGroup.rotation.z = t * 0.22 * m;
  }

  if (S.ringMesh && S.camera) {
    S.ringMesh.quaternion.copy(S.camera.quaternion);
  }

  if (S.dais) {
    S.dais.rotation.z = -t * 0.04 * m;
  }

  if (S.wingL && S.wingR) {
    const flap = Math.sin(t * 1.8 * (0.4 + 0.6 * m)) * 0.09 * m + c.flare * 0.15;
    for (let i = 0; i < S.wingL.length; i++) {
      const phase = i * 0.12;
      const f = Math.sin(t * 1.8 + phase) * 0.06 * m;
      S.wingL[i].rotation.z = flap + f;
      S.wingR[i].rotation.z = -(flap + f);
    }
  }

  if (S.coreGroup) {
    const breath = 1.0 + 0.02 * Math.sin(t * 0.9) + S.pulse * 0.08;
    const scale = S.baseScale * breath;
    S.coreGroup.scale.set(scale, scale, scale);
  }

  updateMaterials();
}

function render() {
  if (S.perfLevel < 2 && S.composer) {
    S.composer.render();
  } else if (S.renderer && S.scene && S.camera) {
    S.renderer.render(S.scene, S.camera);
  }
}

function frame(timeNow) {
  if (!S.running) return;
  const dt = Math.min((timeNow - S.lastTime) / 1000, 0.1);
  S.lastTime = timeNow;

  S.frameAcc += dt;
  S.frameCount++;
  if (S.frameAcc >= 1.0) {
    const fps = S.frameCount / S.frameAcc;
    S.frameAcc = 0;
    S.frameCount = 0;
    if (fps < 30 && S.perfLevel < 2) {
      S.perfLevel++;
      applyPerfLevel();
    }
  }

  step(dt);
  render();

  S.rafId = requestAnimationFrame(frame);
}

function applyPerfLevel() {
  if (!S.renderer) return;
  if (S.perfLevel === 1) {
    S.renderer.setPixelRatio(1.0);
  } else if (S.perfLevel >= 2) {
    S.renderer.setPixelRatio(1.0);
    if (S.particles) S.particles.visible = false;
    if (S.dust) S.dust.visible = false;
  }
}

function renderStill() {
  step(0.016);
  render();
}

function onResize() {
  if (!S.container || !S.renderer || !S.camera) return;
  const w = S.container.clientWidth;
  const h = S.container.clientHeight;
  if (w === 0 || h === 0) return;

  S.camera.aspect = w / h;
  S.camera.updateProjectionMatrix();

  S.renderer.setSize(w, h);
  if (S.composer) S.composer.setSize(w, h);

  const aspect = w / h;
  if (aspect < 1.0) {
    S.baseScale = aspect * 0.85;
  } else if (aspect < 1.4) {
    S.baseScale = 0.92;
  } else {
    S.baseScale = 1.0;
  }
}

/* ════════════════════════════════════════════════════
   PUBLIC ENGINE API (EXPLICITLY ISOLATED)
   ════════════════════════════════════════════════════ */

const Battleground3D = {
  get state() {
    return S.stateName;
  },

  async init({ container, getAudioLevel }) {
    if (S.inited) return;
    S.inited = true;
    S.container = container;
    S.getAudioLevel = getAudioLevel || null;
    S.reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    let gl = null;
    try {
      const probe = document.createElement("canvas");
      gl = probe.getContext("webgl2") || probe.getContext("webgl");
    } catch { /* pass */ }

    if (!gl) {
      S.webgl = false;
      container.classList.add("bg-fallback");
      S.fallbackEl = document.createElement("div");
      S.fallbackEl.className = "orb-fallback";
      container.appendChild(S.fallbackEl);
      return;
    }

    S.renderer = new THREE.WebGLRenderer({
      antialias: true,
      powerPreference: "high-performance",
    });
    S.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    S.renderer.toneMappingExposure = 1.1;
    S.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    S.renderer.setClearColor(VOID);
    container.appendChild(S.renderer.domElement);

    buildScene();

    const size = new THREE.Vector2(container.clientWidth || window.innerWidth, container.clientHeight || window.innerHeight);
    S.composer = new EffectComposer(S.renderer);
    S.composer.addPass(new RenderPass(S.scene, S.camera));
    S.bloomPass = new UnrealBloomPass(size, 0.65, 0.55, 0.2);
    S.composer.addPass(S.bloomPass);
    S.composer.addPass(new OutputPass());

    S.resizeObserver = new ResizeObserver(onResize);
    S.resizeObserver.observe(container);
    onResize();

    if (S.reducedMotion) renderStill();
  },

  setState(name) {
    if (!STATES[name]) return;
    S.stateName = name;
    if (!S.webgl) return;
    if (S.reducedMotion && S.inited && S.renderer) renderStill();
  },

  setAudioLevel(val) {
    if (typeof val === 'number') {
      S.pulse = Math.min(Math.max(val, 0), 1);
    }
  },

  setClusterHealth(map) {
    Object.assign(S.clusterHealth, map);
    if (S.reducedMotion && S.renderer) renderStill();
  },

  resume() {
    if (!S.webgl || S.running || S.reducedMotion) {
      if (S.reducedMotion && S.renderer) renderStill();
      return;
    }
    S.running = true;
    S.lastTime = performance.now();
    S.rafId = requestAnimationFrame(frame);
  },

  pause() {
    S.running = false;
    if (S.rafId) cancelAnimationFrame(S.rafId);
  },

  dispose() {
    this.pause();
    if (S.resizeObserver) S.resizeObserver.disconnect();
    if (S.renderer) {
      S.renderer.dispose();
      if (S.renderer.domElement && S.renderer.domElement.parentNode) {
        S.renderer.domElement.parentNode.removeChild(S.renderer.domElement);
      }
    }
    S.inited = false;
  },
};

export default Battleground3D;
