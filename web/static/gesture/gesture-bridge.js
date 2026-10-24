(function (root, factory) {
  if (typeof module !== "undefined" && module.exports) {
    module.exports = factory();
  } else {
    root.CyraenGestureBridge = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const ROTATE_SPEED = 6.0;
  const ROTATE_CLAMP_X = 1.2;
  const ZOOM_SPEED = 24.0;
  const ZOOM_MIN = 2;
  const ZOOM_MAX = 20;
  const EXPLODE_DISTANCE = 1.6;
  const EXPLODE_LERP = 0.12;
  const HOVER_EMISSIVE = 0.5;
  const SELECT_EMISSIVE = 1.4;

  function clamp(v, lo, hi) {
    return Math.max(lo, Math.min(hi, v));
  }

  // Translates classified intents (from gesture-engine, which knows nothing
  // about Three.js) into concrete scene mutations. This is the only module
  // allowed to touch camera/modelGroup/meshes.
  function createGestureBridge({ THREE, camera, modelGroup, parts: initialParts, onPartResolved, onLockChange } = {}) {
    const raycaster = new THREE.Raycaster();
    const parts = [];
    const meshes = [];
    let exploded = false;
    let hoveredPart = null;
    let selectedPart = null;

    // Shared setup for every part, whether present at construction time or
    // added later at runtime via addPart() - both go through the same path
    // so newly-added objects explode/select/highlight exactly like the rest.
    function registerPart(p) {
      p.mesh.userData.part = p.name;
      p.mesh.userData.restPosition = p.mesh.position.clone();
      p.mesh.userData.explodeOffset = 0; // 0..1 tween progress
      p.mesh.userData.baseEmissive =
        p.mesh.material && "emissiveIntensity" in p.mesh.material ? p.mesh.material.emissiveIntensity : 0;
      parts.push(p);
      meshes.push(p.mesh);
      if (p.mesh.parent !== modelGroup) modelGroup.add(p.mesh);
    }

    for (const p of initialParts || []) registerPart(p);

    function setEmissive(mesh, intensity) {
      if (mesh && mesh.material && "emissiveIntensity" in mesh.material) {
        mesh.material.emissiveIntensity = intensity;
      }
    }

    function raycastPart(ndcX, ndcY) {
      raycaster.setFromCamera({ x: ndcX, y: ndcY }, camera);
      const hits = raycaster.intersectObjects(meshes, false);
      return hits.length ? parts.find((p) => p.mesh === hits[0].object) : null;
    }

    function toNdc(x, y) {
      // gesture-engine coords are image-space (0..1, y-down); Three.js NDC is (-1..1, y-up).
      return { x: x * 2 - 1, y: -(y * 2 - 1) };
    }

    function handleHover(intent) {
      const { x, y } = toNdc(intent.x, intent.y);
      const hit = raycastPart(x, y);
      if (hoveredPart && hoveredPart !== hit && hoveredPart !== selectedPart) {
        setEmissive(hoveredPart.mesh, hoveredPart.mesh.userData.baseEmissive);
      }
      hoveredPart = hit;
      if (hit && hit !== selectedPart) setEmissive(hit.mesh, HOVER_EMISSIVE);
      if (onPartResolved) onPartResolved({ gesture: "hover", part: hit ? hit.name : null, ts: intent.ts });
    }

    function handleSelect(intent) {
      const { x, y } = toNdc(intent.x, intent.y);
      const hit = raycastPart(x, y);
      if (selectedPart && selectedPart !== hit) {
        setEmissive(selectedPart.mesh, selectedPart.mesh.userData.baseEmissive);
      }
      selectedPart = hit;
      if (hit) setEmissive(hit.mesh, SELECT_EMISSIVE);
      if (onPartResolved) onPartResolved({ gesture: "select", part: hit ? hit.name : null, ts: intent.ts });
    }

    function handleRotate(intent) {
      modelGroup.rotation.y += intent.dx * ROTATE_SPEED;
      modelGroup.rotation.x = clamp(modelGroup.rotation.x + intent.dy * ROTATE_SPEED, -ROTATE_CLAMP_X, ROTATE_CLAMP_X);
    }

    function handleZoom(intent) {
      camera.position.z = clamp(camera.position.z - intent.delta * ZOOM_SPEED, ZOOM_MIN, ZOOM_MAX);
    }

    function handleExplode() {
      exploded = !exploded;
    }

    function handleLock(intent) {
      if (onLockChange) onLockChange(intent.locked);
    }

    function onIntent(intent) {
      switch (intent.type) {
        case "hover":
          return handleHover(intent);
        case "select":
          return handleSelect(intent);
        case "rotate":
          return handleRotate(intent);
        case "zoom":
          return handleZoom(intent);
        case "explode":
          return handleExplode();
        case "lock":
          return handleLock(intent);
        default:
          return undefined;
      }
    }

    // Called once per render frame from the main loop to tween explode offsets.
    function update() {
      const target = exploded ? 1 : 0;
      for (const p of parts) {
        const ud = p.mesh.userData;
        ud.explodeOffset += (target - ud.explodeOffset) * EXPLODE_LERP;
        if (Math.abs(target - ud.explodeOffset) < 0.001) ud.explodeOffset = target;
        p.mesh.position.copy(ud.restPosition).addScaledVector(p.explodeDirection, ud.explodeOffset * EXPLODE_DISTANCE);
      }
    }

    function isExploded() {
      return exploded;
    }

    // Adds a new object at runtime (e.g. from the "Parca ekle" UI). It joins
    // the same explode/select/raycast pipeline as every part built in.
    function addPart(p) {
      registerPart(p);
      return p;
    }

    function removePart(name) {
      const idx = parts.findIndex((p) => p.name === name);
      if (idx === -1) return false;
      const [p] = parts.splice(idx, 1);
      const meshIdx = meshes.indexOf(p.mesh);
      if (meshIdx !== -1) meshes.splice(meshIdx, 1);
      modelGroup.remove(p.mesh);
      if (hoveredPart === p) hoveredPart = null;
      if (selectedPart === p) selectedPart = null;
      return true;
    }

    return { onIntent, update, isExploded, addPart, removePart };
  }

  return { createGestureBridge };
});
