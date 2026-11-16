  const wheelTex = (() => {
    const c = document.createElement("canvas"); c.width = c.height = 256; const g = c.getContext("2d");
    g.translate(128, 128);
    g.fillStyle = "#07090d"; g.beginPath(); g.arc(0, 0, 128, 0, 7); g.fill();
    g.fillStyle = "#11161f"; g.beginPath(); g.arc(0, 0, 90, 0, 7); g.fill();
    g.strokeStyle = "#d5dde8"; g.lineWidth = 9; g.beginPath(); g.arc(0, 0, 86, 0, 7); g.stroke();
    g.lineCap = "round"; g.lineWidth = 15;
    for (let i = 0; i < 5; i++) { const a = (i / 5) * Math.PI * 2 - Math.PI / 2; g.beginPath(); g.moveTo(Math.cos(a) * 18, Math.sin(a) * 18); g.lineTo(Math.cos(a) * 82, Math.sin(a) * 82); g.stroke(); }
    g.fillStyle = "#d5dde8"; g.beginPath(); g.arc(0, 0, 22, 0, 7); g.fill();
    g.fillStyle = "#1b2330"; g.beginPath(); g.arc(0, 0, 9, 0, 7); g.fill();
    const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4; return t;
  })();
