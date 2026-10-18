import { useEffect, useRef } from "react";
import { PX_PER_M, worldRef } from "./ref";
import type { ViewInfo } from "./WorldScene";

const SIZE = 170;
let baseImage: Promise<HTMLCanvasElement> | null = null;

/** Average colour of each tileset tile (gid → rgb). */
async function tileColours(): Promise<[number, number, number][]> {
  const img = new Image();
  img.src = "/assets/tiles/city.png";
  await img.decode();
  const c = document.createElement("canvas");
  c.width = img.width;
  c.height = img.height;
  const g = c.getContext("2d")!;
  g.drawImage(img, 0, 0);
  const cols: [number, number, number][] = [[0, 0, 0]];
  for (let i = 0; i < (img.width / 16) * (img.height / 16); i++) {
    const d = g.getImageData((i % 8) * 16, Math.floor(i / 8) * 16, 16, 16).data;
    let r = 0, gg = 0, b = 0, n = 0;
    for (let k = 0; k < d.length; k += 4) if (d[k + 3] > 0) { r += d[k]; gg += d[k + 1]; b += d[k + 2]; n++; }
    cols.push(n ? [r / n, gg / n, b / n] : [0, 0, 0]);
  }
  return cols;
}

/** One pixel per tile: the top-most non-empty layer wins. */
export function buildBase(): Promise<HTMLCanvasElement> {
  baseImage ??= (async () => {
    const [tmj, cols] = await Promise.all([fetch("/assets/maps/indiranagar.tmj").then((r) => r.json()), tileColours()]);
    const W = tmj.width as number, H = tmj.height as number;
    const layers = (tmj.layers as { type: string; name: string; data: number[] }[]).filter((l) => l.type === "tilelayer");
    const order = ["decor", "buildings", "rail", "roads", "landuse", "ground"].map((n) => layers.find((l) => l.name === n)!);
    const c = document.createElement("canvas");
    c.width = W;
    c.height = H;
    const g = c.getContext("2d")!;
    const im = g.createImageData(W, H);
    for (let k = 0; k < W * H; k++) {
      const gid = order.map((l) => l.data[k]).find((v) => v) ?? 0;
      const [r, gg, b] = cols[gid] ?? [0, 0, 0];
      im.data.set([r, gg, b, 255], k * 4);
    }
    g.putImageData(im, 0, 0);
    return c;
  })();
  return baseImage;
}

/** Minimap (`minimap`): map overview, viewport rectangle, click to move the camera. */
export function Minimap() {
  const cv = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    let alive = true;
    let base: HTMLCanvasElement | null = null;
    const draw = (v: ViewInfo | null) => {
      const g = cv.current?.getContext("2d");
      if (!g || !base) return;
      g.imageSmoothingEnabled = true;
      g.drawImage(base, 0, 0, SIZE, SIZE);
      if (v) {
        const sx = SIZE / v.mapW, sy = SIZE / v.mapH;
        g.strokeStyle = "#2dd4bf";
        g.lineWidth = 1.5;
        g.strokeRect(v.x * sx, v.y * sy, v.w * sx, v.h * sy);
      }
    };
    buildBase().then((b) => {
      if (!alive) return;
      base = b;
      draw(worldRef.view);
    });
    worldRef.listeners.add(draw);
    return () => {
      alive = false;
      worldRef.listeners.delete(draw);
    };
  }, []);
  const onClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const sc = worldRef.scene;
    if (!sc) return;
    const r = e.currentTarget.getBoundingClientRect();
    const x = ((e.clientX - r.left) / r.width) * sc.mapW;
    const y = ((e.clientY - r.top) / r.height) * sc.mapH;
    sc.focusM(x / PX_PER_M, y / PX_PER_M);
  };
  return (
    <div className="minimap" data-testid="minimap">
      <canvas ref={cv} width={SIZE} height={SIZE} onClick={onClick} />
    </div>
  );
}
