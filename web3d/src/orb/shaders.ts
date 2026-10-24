// Zoey OS orb'unun parcacik shader'lari (zoeyos.com hero orb'u ile ayni formul):
// fibonacci kuresine dizili noktalar, iki sinus dalgasiyla organik yuzey, sese gore nefes,
// ekvatordan kutba renk gecisi, derinlige gore boy/saydamlik. Additive karisim + Bloom.

export const orbVertex = /* glsl */ `
uniform float u_time;
uniform float u_radius;
uniform float u_noise_amp;
uniform float u_birth_progress;
uniform float u_voice_amp;

attribute vec3 a_basePosition;

varying float v_depth;
varying float v_alpha;
varying float v_latitude;

void main() {
  vec3 norm = normalize(a_basePosition);
  vec3 spherePos = norm * u_radius;

  // Iki sinus dalgasinin carpimi: organik yuzey bukulmesi
  float waveDisp = sin(a_basePosition.x * 3.0 + u_time * 0.8) *
                   sin(a_basePosition.y * 2.0 + u_time * 0.6) *
                   u_noise_amp;
  spherePos += norm * waveDisp;

  // Ses: genlikle disa dogru nefes alir
  spherePos *= (1.0 + u_voice_amp * 0.15);

  vec3 emerged = mix(vec3(0.0), spherePos, smoothstep(0.0, 1.0, u_birth_progress));

  vec4 mvPos = modelViewMatrix * vec4(emerged, 1.0);
  gl_Position = projectionMatrix * mvPos;

  // 0 = kurenin arkasi, 1 = kameraya bakan on yuz
  float rawDepth = dot(norm, vec3(0.0, 0.0, 1.0));
  v_depth = rawDepth * 0.5 + 0.5;

  float ptSize = mix(1.9, 4.4, v_depth);
  float birthSizeBoost = 1.0 + (1.0 - smoothstep(0.0, 0.7, u_birth_progress)) * 0.29;
  ptSize = ptSize * birthSizeBoost * (1.0 + u_voice_amp * 0.2);
  gl_PointSize = ptSize * (8.0 / -mvPos.z);

  v_alpha = smoothstep(0.0, 0.3, u_birth_progress);
  v_latitude = a_basePosition.y;
}
`

export const orbFragment = /* glsl */ `
uniform vec3  u_color_equator;
uniform vec3  u_color_pole;
uniform float u_brightness;
uniform float u_birth_progress;

varying float v_depth;
varying float v_alpha;
varying float v_latitude;

void main() {
  vec2 uv = gl_PointCoord - 0.5;
  float r = length(uv);
  if (r > 0.5) discard;

  // cekirdek + hale + dagilan isima
  float core = smoothstep(0.35, 0.0, r);
  float halo = smoothstep(0.5, 0.1, r) * 0.4;
  float glow = smoothstep(0.5, 0.0, r) * 0.25;
  float intensity = core + halo + glow;

  // ekvator -> kutup renk gecisi
  vec3 color = mix(u_color_equator, u_color_pole, abs(v_latitude));

  // dogarken beyaza kayan kisa parlama
  float birthGlow = 1.0 - smoothstep(0.0, 0.7, u_birth_progress);
  color = mix(color, vec3(1.0, 0.95, 0.9), birthGlow * 0.24);
  float birthBrightBoost = 1.0 + birthGlow * 0.3;

  float depthAlpha = 0.18 + 0.67 * v_depth;
  float glowMult = v_depth > 0.45 ? 1.0 + (v_depth - 0.45) * 1.2 : 0.7;
  float alpha = intensity * v_alpha * depthAlpha;

  // parlak renkleri biraz bastir, koyulari koru
  float lum = dot(color, vec3(0.299, 0.587, 0.114));
  float lumCompensation = mix(1.0, 0.7, lum);

  gl_FragColor = vec4(
    color * u_brightness * birthBrightBoost * glowMult * intensity * lumCompensation,
    alpha
  );
}
`
