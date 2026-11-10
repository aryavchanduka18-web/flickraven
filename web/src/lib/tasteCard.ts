/** Draws the shareable Taste DNA card on a canvas and returns a PNG blob. Only called from an explicit click. */
export async function tasteCardPng(p: { name: string; traits: { label: string; you: number }[]; personality: string | null; genres: string[] }): Promise<Blob> {
  const w = 1080, h = 1350, cv = document.createElement("canvas");
  cv.width = w; cv.height = h;
  const g = cv.getContext("2d")!;
  g.fillStyle = "#080808"; g.fillRect(0, 0, w, h);
  g.fillStyle = "#fff"; g.font = "800 54px system-ui, sans-serif"; g.fillText("Flick", 70, 110);
  const fw = g.measureText("Flick").width;
  g.fillStyle = "#e0263f"; g.fillText("Raven", 70 + fw, 110);
  g.fillStyle = "#fff"; g.font = "700 76px system-ui, sans-serif"; g.fillText("My Taste DNA", 70, 230);
  g.fillStyle = "#a3a3a3"; g.font = "400 34px system-ui, sans-serif";
  if (p.genres.length) g.fillText(p.genres.slice(0, 3).join(" · "), 70, 290);
  const top = [...p.traits].sort((a, b) => b.you - a.you).slice(0, 6);
  top.forEach((t, i) => {
    const y = 400 + i * 110;
    g.fillStyle = "#e5e5e5"; g.font = "600 36px system-ui, sans-serif"; g.fillText(t.label, 70, y);
    g.fillStyle = "#ffffff1a"; g.fillRect(70, y + 22, 940, 16);
    g.fillStyle = "#e0263f"; g.fillRect(70, y + 22, (940 * t.you) / 100, 16);
  });
  if (p.personality) {
    g.fillStyle = "#d4d4d4"; g.font = "400 32px system-ui, sans-serif";
    const words = p.personality.split(" "); let line = "", y = 1110;
    for (const word of words) {
      if (g.measureText(line + word).width > 940) { g.fillText(line, 70, y); line = ""; y += 44; if (y > 1260) break; }
      line += word + " ";
    }
    if (y <= 1260) g.fillText(line, 70, y);
  }
  g.fillStyle = "#737373"; g.font = "400 28px system-ui, sans-serif"; g.fillText("flickraven.onrender.com", 70, 1310);
  return new Promise((res, rej) => cv.toBlob((b) => (b ? res(b) : rej(new Error("png"))), "image/png"));
}
