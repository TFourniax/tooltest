(function () {
  "use strict";

  const THREE = window.THREE;
  const canvas = document.querySelector("[data-sphaira]");
  if (!THREE || !canvas) {
    document.documentElement.classList.add("no-webgl");
    return;
  }

  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const labMode = canvas.hasAttribute("data-lab-scene");
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(labMode ? 34 : 38, 1, .1, 100);
  camera.position.set(0, .2, labMode ? 6.7 : 6.2);

  const mobile = window.innerWidth < 820;
  const count = mobile ? 820 : (labMode ? 2400 : 1750);
  const radius = labMode ? 2.15 : 1.9;
  const base = new Float32Array(count * 3);
  const positions = new Float32Array(count * 3);
  const colors = new Float32Array(count * 3);
  const disorder = new Float32Array(count);
  const witnessed = new Float32Array(count);
  const jitter = new Float32Array(count * 3);
  const goldenAngle = Math.PI * (3 - Math.sqrt(5));

  for (let i = 0; i < count; i += 1) {
    const y = 1 - (i / (count - 1)) * 2;
    const radial = Math.sqrt(1 - y * y);
    const angle = goldenAngle * i;
    base[i * 3] = Math.cos(angle) * radial * radius;
    base[i * 3 + 1] = y * radius;
    base[i * 3 + 2] = Math.sin(angle) * radial * radius;
    jitter[i * 3] = Math.random() - .5;
    jitter[i * 3 + 1] = Math.random() - .5;
    jitter[i * 3 + 2] = Math.random() - .5;
  }
  positions.set(base);

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
  const material = new THREE.PointsMaterial({
    size: mobile ? .047 : .035,
    vertexColors: true,
    transparent: true,
    opacity: .95,
    sizeAttenuation: true
  });
  const points = new THREE.Points(geometry, material);
  const group = new THREE.Group();
  group.add(points);
  scene.add(group);

  const wire = new THREE.LineSegments(
    new THREE.WireframeGeometry(new THREE.IcosahedronGeometry(radius * .985, 2)),
    new THREE.LineBasicMaterial({ color: 0x2a2340, transparent: true, opacity: labMode ? .72 : .5 })
  );
  group.add(wire);

  const ring = new THREE.Mesh(
    new THREE.TorusGeometry(radius * 1.06, .007, 8, 180),
    new THREE.MeshBasicMaterial({ color: 0xa98cff })
  );
  ring.rotation.x = Math.PI / 2;
  group.add(ring);

  const ringGlow = new THREE.Mesh(
    new THREE.TorusGeometry(radius * 1.06, .035, 8, 180),
    new THREE.MeshBasicMaterial({ color: 0x6544df, transparent: true, opacity: .28 })
  );
  ringGlow.rotation.x = Math.PI / 2;
  group.add(ringGlow);

  const pulses = [];
  const pulseGeometry = new THREE.SphereGeometry(.032, 7, 7);
  const pulseMaterial = new THREE.MeshBasicMaterial({ color: 0xefede8 });
  const ink = new THREE.Color(0xefede8);
  const grey = new THREE.Color(0x4a474d);
  const violet = new THREE.Color(0xa98cff);
  const mixed = new THREE.Color();

  let sweepY = -radius;
  let sweepDirection = 1;
  let lastFrame = performance.now();
  let pulseClock = 0;
  let pointerX = 0;
  let pointerY = 0;
  let scrollPosition = 0;
  let visible = true;
  let speed = labMode ? 1 : .75;
  let impact = labMode ? 1 : .8;

  function spawnPulse() {
    const index = Math.floor(Math.random() * count);
    const pulse = new THREE.Mesh(pulseGeometry, pulseMaterial.clone());
    const direction = new THREE.Vector3(base[index * 3], base[index * 3 + 1], base[index * 3 + 2]).normalize();
    pulse.position.copy(direction).multiplyScalar(radius * 2.65);
    pulse.userData = { index, direction, progress: 0 };
    group.add(pulse);
    pulses.push(pulse);
  }

  function resize() {
    const width = Math.max(1, canvas.clientWidth);
    const height = Math.max(1, canvas.clientHeight);
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    if (reducedMotion) renderer.render(scene, camera);
  }

  window.addEventListener("pointermove", function (event) {
    pointerX = event.clientX / window.innerWidth - .5;
    pointerY = event.clientY / window.innerHeight - .5;
  }, { passive: true });
  window.addEventListener("scroll", function () { scrollPosition = window.scrollY; }, { passive: true });
  window.addEventListener("resize", resize);
  resize();

  if ("IntersectionObserver" in window) {
    new IntersectionObserver(function (entries) {
      visible = entries[0]?.isIntersecting ?? true;
    }, { rootMargin: "120px" }).observe(canvas);
  }

  document.querySelectorAll("[data-scene-control]").forEach(function (control) {
    const output = document.querySelector(`[data-scene-value="${control.dataset.sceneControl}"]`);
    function update() {
      const value = Number(control.value);
      if (control.dataset.sceneControl === "speed") speed = value / 100;
      if (control.dataset.sceneControl === "impact") impact = value / 100;
      if (output) output.textContent = `${value}%`;
    }
    control.addEventListener("input", update);
    update();
  });

  function animate(now) {
    const delta = Math.min(.05, (now - lastFrame) / 1000);
    lastFrame = now;
    if (!visible && !labMode) {
      requestAnimationFrame(animate);
      return;
    }

    if (!reducedMotion) {
      pulseClock += delta * impact;
      while (pulseClock > .12) {
        pulseClock -= .12;
        if (pulses.length < (mobile ? 18 : 38)) spawnPulse();
      }

      for (let k = pulses.length - 1; k >= 0; k -= 1) {
        const pulse = pulses[k];
        pulse.userData.progress += delta * 1.6 * Math.max(.25, impact);
        const distance = radius * 2.65 - (radius * 1.65) * Math.min(1, pulse.userData.progress);
        pulse.position.copy(pulse.userData.direction).multiplyScalar(distance);
        pulse.material.opacity = 1 - Math.max(0, pulse.userData.progress - .72) / .28;
        pulse.material.transparent = true;
        if (pulse.userData.progress >= 1) {
          const source = pulse.userData.index;
          for (let i = 0; i < count; i += 1) {
            const dx = base[i * 3] - base[source * 3];
            const dy = base[i * 3 + 1] - base[source * 3 + 1];
            const dz = base[i * 3 + 2] - base[source * 3 + 2];
            const distanceSquared = dx * dx + dy * dy + dz * dz;
            if (distanceSquared < .36) {
              disorder[i] = Math.min(1, disorder[i] + .6 * (1 - distanceSquared / .36));
              witnessed[i] = Math.max(0, witnessed[i] - .65);
            }
          }
          group.remove(pulse);
          pulse.material.dispose();
          pulses.splice(k, 1);
        }
      }

      sweepY += sweepDirection * delta * .58 * Math.max(.2, speed);
      if (sweepY > radius * 1.05) sweepDirection = -1;
      if (sweepY < -radius * 1.05) sweepDirection = 1;
      ring.position.y = sweepY;
      ringGlow.position.y = sweepY;
      const ringScale = Math.sqrt(Math.max(0, radius * radius - Math.min(radius * radius, sweepY * sweepY))) / radius;
      ring.scale.set(ringScale, ringScale, 1);
      ringGlow.scale.set(ringScale, ringScale, 1);
      group.rotation.y += delta * .065 * Math.max(.2, speed);
    }

    const time = now / 1000;
    for (let i = 0; i < count; i += 1) {
      const drift = disorder[i];
      if (!reducedMotion) {
        if (Math.abs(base[i * 3 + 1] - sweepY) < .13) {
          disorder[i] = Math.max(0, drift - delta * 2.25 * speed);
          witnessed[i] = Math.min(1, witnessed[i] + delta * 3.1 * speed);
        }
        witnessed[i] = Math.max(0, witnessed[i] - delta * .05);
      }
      const scatter = drift * .58;
      const wobble = Math.sin(time * 2 + i) * .02 * drift;
      positions[i * 3] = base[i * 3] + jitter[i * 3] * scatter + wobble;
      positions[i * 3 + 1] = base[i * 3 + 1] + jitter[i * 3 + 1] * scatter;
      positions[i * 3 + 2] = base[i * 3 + 2] + jitter[i * 3 + 2] * scatter - wobble;
      mixed.copy(ink).lerp(grey, Math.min(1, drift * 1.4)).lerp(violet, witnessed[i]);
      colors[i * 3] = mixed.r;
      colors[i * 3 + 1] = mixed.g;
      colors[i * 3 + 2] = mixed.b;
    }

    geometry.attributes.position.needsUpdate = true;
    geometry.attributes.color.needsUpdate = true;
    const targetX = pointerX * (labMode ? .9 : .6);
    camera.position.x += (targetX - camera.position.x) * .035;
    const targetY = .2 - pointerY * .4 - (labMode ? 0 : scrollPosition * .0011);
    camera.position.y += (targetY - camera.position.y) * .035;
    camera.lookAt(0, 0, 0);
    group.position.x = labMode || mobile ? 0 : 1.15;
    renderer.render(scene, camera);
    if (!reducedMotion) requestAnimationFrame(animate);
  }

  requestAnimationFrame(animate);
})();
