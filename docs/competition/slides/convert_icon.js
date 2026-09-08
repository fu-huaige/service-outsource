const sharp = require("sharp");
const path = require("path");

const src = path.join(__dirname, "..", "assets", "icon.svg");
const dest = path.join(__dirname, "..", "assets", "icon.png");

sharp(src, { density: 600 })
  .resize(1200, 1200)
  .png()
  .toFile(dest)
  .then(() => console.log("wrote", dest))
  .catch((err) => {
    console.error(err);
    process.exit(1);
  });
