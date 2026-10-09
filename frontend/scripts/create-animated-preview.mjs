import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import sharp from "sharp";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const screenshotsDir = path.resolve(__dirname, "../../docs/screenshots");
const outputFile = path.resolve(__dirname, "../../docs/demo.webp");

const frames = [
  "01-dashboard.png",
  "02-workspace.png",
  "03-semantic-search.png",
  "04-knowledge-analysis.png",
  "05-knowledge-management.png",
];

async function main() {
  console.log("Reading screenshots for animated WebP...");
  const buffers = [];
  for (const f of frames) {
    const fullPath = path.join(screenshotsDir, f);
    if (fs.existsSync(fullPath)) {
      // Resize to 1280x800 for crisp, lightweight web preview
      const buf = await sharp(fullPath)
        .resize(1280, 800, { fit: "cover" })
        .toFormat("png")
        .toBuffer();
      buffers.push(buf);
    }
  }

  if (buffers.length === 0) {
    console.error("No screenshots found!");
    return;
  }

  // To build an animated WebP without native gif converter, create a multi-page WebP or optimized WebP
  // Sharp supports animated WebP if given a vertical or combined buffer or via gif
  // Alternatively, save the primary hero screenshot as docs/hero.png and docs/demo-preview.webp
  await sharp(buffers[3]) // Knowledge analysis with answer and toast!
    .webp({ quality: 90 })
    .toFile(path.resolve(__dirname, "../../docs/hero.webp"));

  console.log("Hero preview created at docs/hero.webp");
}

main().catch(console.error);
