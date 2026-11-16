  const BODIES = {
    coupe_front: { L: 4.6, W: 1.86, g: 0.28, r: 0.345, ax: [1.42, -1.28],
      belt: [[-2.3, 0.72], [-1.95, 0.9], [-1.3, 0.95], [0, 0.94], [0.55, 0.93], [1.4, 0.86], [2.0, 0.72], [2.3, 0.55]],
      roof: [[-1.75, 0.93], [-1.15, 1.2], [-0.6, 1.32], [-0.1, 1.31], [0.55, 0.93]], paint: [[-0.72, -0.08]], glass: [-1.3, 0.45], tub: 1.7 },
    coupe_rear: { L: 4.5, W: 1.84, g: 0.27, r: 0.345, ax: [1.32, -1.13],
      belt: [[-2.25, 0.7], [-1.9, 0.86], [-1.2, 0.93], [0.2, 0.93], [0.95, 0.9], [1.6, 0.8], [2.05, 0.66], [2.25, 0.52]],
      roof: [[-1.95, 0.86], [-1.2, 1.1], [-0.45, 1.27], [0.1, 1.3], [0.45, 1.24], [1.0, 0.9]], paint: [[-1.95, -1.25], [-0.45, 0.45]], glass: [-1.2, 0.9], tub: 1.75 },
    coupe_mid: { L: 4.5, W: 1.92, g: 0.24, r: 0.345, ax: [1.33, -1.3],
      belt: [[-2.25, 0.76], [-1.9, 0.94], [-1.0, 0.98], [0.3, 0.9], [1.1, 0.83], [1.7, 0.69], [2.1, 0.55], [2.25, 0.45]],
      roof: [[-1.3, 0.97], [-0.8, 1.13], [-0.25, 1.2], [0.3, 1.18], [1.12, 0.83]], paint: [[-1.3, -0.85], [-0.3, 0.3]], glass: [-0.75, 1.02], tub: 1.3 },
    sedan: { L: 4.85, W: 1.86, g: 0.3, r: 0.34, ax: [1.5, -1.4],
      belt: [[-2.42, 0.76], [-2.15, 0.96], [-1.5, 1.0], [0, 0.99], [0.75, 0.97], [1.6, 0.92], [2.15, 0.78], [2.42, 0.58]],
      roof: [[-1.6, 1.0], [-1.05, 1.36], [-0.5, 1.45], [0.1, 1.44], [0.78, 0.97]], paint: [[-1.0, 0.05]], glass: [-1.4, 0.68] },
    hatch: { L: 4.3, W: 1.8, g: 0.3, r: 0.33, ax: [1.33, -1.27],
      belt: [[-2.15, 0.78], [-1.95, 0.98], [-1.0, 1.0], [0.6, 0.98], [1.35, 0.92], [1.9, 0.78], [2.15, 0.58]],
      roof: [[-2.06, 0.99], [-1.72, 1.36], [-1.0, 1.47], [0, 1.46], [0.66, 0.98]], paint: [[-1.62, -0.05]], glass: [-1.8, 0.56] },
    wagon: { L: 4.8, W: 1.86, g: 0.3, r: 0.34, ax: [1.5, -1.38],
      belt: [[-2.4, 0.78], [-2.2, 0.98], [-1.2, 1.0], [0.75, 0.97], [1.6, 0.92], [2.15, 0.78], [2.4, 0.58]],
      roof: [[-2.33, 0.99], [-1.98, 1.38], [-1.0, 1.46], [0.1, 1.45], [0.78, 0.97]], paint: [[-1.88, 0.05]], glass: [-2.05, 0.68] },
    suv: { L: 4.75, W: 1.95, g: 0.42, r: 0.4, ax: [1.45, -1.37],
      belt: [[-2.37, 0.96], [-2.2, 1.16], [-1.2, 1.2], [0.8, 1.17], [1.6, 1.12], [2.1, 0.98], [2.37, 0.74]],
      roof: [[-2.31, 1.19], [-2.02, 1.62], [-1.0, 1.72], [0.15, 1.7], [0.86, 1.17]], paint: [[-1.92, 0.1]], glass: [-2.05, 0.76] },
    truck: { L: 5.5, W: 2.0, g: 0.45, r: 0.42, ax: [1.85, -1.75],
      belt: [[-2.75, 1.04], [-2.6, 1.24], [-0.6, 1.26], [1.2, 1.24], [2.0, 1.2], [2.5, 1.08], [2.75, 0.82]],
      roof: [[-0.44, 1.26], [-0.36, 1.76], [0.2, 1.85], [0.75, 1.83], [1.32, 1.24]], paint: [[-0.34, 0.7]], glass: [-0.3, 1.2], bed: [-2.58, -0.5] },
    van: { L: 5.0, W: 1.98, g: 0.36, r: 0.37, ax: [1.62, -1.5],
      belt: [[-2.5, 0.96], [-2.4, 1.18], [-1.0, 1.2], [1.6, 1.15], [2.2, 1.02], [2.5, 0.74]],
      roof: [[-2.46, 1.19], [-2.3, 1.8], [-1.0, 1.9], [0.9, 1.88], [1.78, 1.15]], paint: [[-2.22, 0.85]], glass: [-2.15, 1.62] },
  };
  function bodySpec(shape) {
    const body = (shape && shape.body) || "coupe", layout = (shape && shape.layout) || "front";
    const open = body === "convertible";
    const base = BODIES[body === "coupe" || open ? "coupe_" + (layout === "rear" || layout === "mid" ? layout : "front") : body] || BODIES.coupe_front;
    if (!open) return base;
    /* open top: keep the windscreen, drop the roof, show the cabin */
    const cowl = base.roof[base.roof.length - 1], top = Math.max(...base.roof.map((p) => p[1]));
    return { ...base, roof: [[cowl[0] - 0.6, top - 0.06], cowl], paint: [], glass: [cowl[0] - 0.6, cowl[0]], cabin: [cowl[0] - base.tub, cowl[0] - 0.14] };
  }
  /* a smooth curve through points that never overshoots them */
  const curve = (pts) => {
    const n = pts.length, d = [], m = new Array(n);
    for (let i = 0; i < n - 1; i++) d.push((pts[i + 1][1] - pts[i][1]) / (pts[i + 1][0] - pts[i][0]));
    m[0] = d[0]; m[n - 1] = d[n - 2];
    for (let i = 1; i < n - 1; i++) m[i] = d[i - 1] * d[i] <= 0 ? 0 : (2 * d[i - 1] * d[i]) / (d[i - 1] + d[i]);
    return (x) => {
      if (x <= pts[0][0]) return pts[0][1];
      if (x >= pts[n - 1][0]) return pts[n - 1][1];
      let i = 0; while (x > pts[i + 1][0]) i++;
      const h = pts[i + 1][0] - pts[i][0], t = (x - pts[i][0]) / h, t2 = t * t, t3 = t2 * t;
      return (2 * t3 - 3 * t2 + 1) * pts[i][1] + (t3 - 2 * t2 + t) * h * m[i] + (-2 * t3 + 3 * t2) * pts[i + 1][1] + (t3 - t2) * h * m[i + 1];
    };
  };
  /* skin a row of cross-sections; matOf picks the material for each panel */
  const loft = (rings, closed, matOf, nMat) => {
    const K = rings[0].length, pos = [];
    rings.forEach((ring) => ring.forEach((p) => pos.push(p[0], p[1], p[2])));
    const buckets = Array.from({ length: nMat }, () => []);
    for (let i = 0; i < rings.length - 1; i++) for (let j = 0; j < (closed ? K : K - 1); j++) {
      const a = i * K + j, b = i * K + ((j + 1) % K), c = (i + 1) * K + j, e = (i + 1) * K + ((j + 1) % K);
      buckets[matOf((rings[i][0][0] + rings[i + 1][0][0]) / 2, j)].push(a, c, b, b, c, e);
    }
    const geo = new THREE.BufferGeometry(); geo.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
    const index = []; let start = 0;
    buckets.forEach((bucket, m) => { geo.addGroup(start, bucket.length, m); start += bucket.length; bucket.forEach((v) => index.push(v)); });
    geo.setIndex(index); geo.computeVertexNormals(); return geo;
  };

