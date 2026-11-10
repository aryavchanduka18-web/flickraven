/** Draws a mission-completion card on a canvas and returns a PNG blob. Only called from an explicit click. */
export const completedOn = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" }) : null);

export async function missionCardPng(p: { title: string; description: string; goal: number; date: string | null }): Promise<Blob> {
  const w = 1080, h = 1080, cv = document.createElement("canvas");
  cv.width = w; cv.height = h;
  const g = cv.getContext("2d")!;
  const wrap = (text: string, x: number, y: number, max: number, lh: number) => {
    let line = "";
    for (const word of text.split(" ")) {
      if (g.measureText(line + word).width > max) { g.fillText(line.trim(), x, y); line = ""; y += lh; }
      line += word + " ";
    }
    g.fillText(line.trim(), x, y);
    return y;
  };
  g.fillStyle = "#080808"; g.fillRect(0, 0, w, h);
  g.fillStyle = "#fff"; g.font = "800 54px system-ui, sans-serif"; g.fillText("Flick", 70, 110);
  const fw = g.measureText("Flick").width;
  g.fillStyle = "#e0263f"; g.fillText("Raven", 70 + fw, 110);
  g.fillStyle = "#e0263f"; g.font = "700 34px system-ui, sans-serif"; g.fillText("DISCOVERY MISSION COMPLETE", 70, 300);
  g.fillStyle = "#fff"; g.font = "800 84px system-ui, sans-serif";
  const y = wrap(p.title, 70, 410, 940, 96);
  g.fillStyle = "#d4d4d4"; g.font = "400 38px system-ui, sans-serif";
  wrap(p.description, 70, y + 90, 940, 52);
  g.fillStyle = "#ffffff1a"; g.fillRect(70, 860, 940, 16);
  g.fillStyle = "#e0263f"; g.fillRect(70, 860, 940, 16);
  g.fillStyle = "#e5e5e5"; g.font = "600 36px system-ui, sans-serif";
  g.fillText(`${p.goal} of ${p.goal}${p.date ? ` · completed ${p.date}` : ""}`, 70, 930);
  g.fillStyle = "#737373"; g.font = "400 28px system-ui, sans-serif"; g.fillText("flickraven.onrender.com", 70, 1030);
  return new Promise((res, rej) => cv.toBlob((b) => (b ? res(b) : rej(new Error("png"))), "image/png"));
}
