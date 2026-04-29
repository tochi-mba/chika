/**
 * generate_icons.js — Run with Node.js to generate PNG icons from SVG
 *
 * Usage: node generate_icons.js
 * Requires: npm install canvas (or use an online SVG-to-PNG converter)
 *
 * The Chika lightning bolt logo: polygon 13,2 3,14 12,14 11,22 21,10 12,10
 */

// If you have `canvas` installed:
// const { createCanvas } = require('canvas')
//
// Otherwise, you can:
// 1. Open icons.svg in a browser and screenshot each size
// 2. Use Inkscape: inkscape --export-png=icon16.png -w 16 icons.svg
// 3. Use ImageMagick: convert -background none icons.svg -resize 16 icon16.png

const svgTemplate = (size) => `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24">
  <rect width="24" height="24" rx="5" fill="#09090d"/>
  <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" fill="#6c63ff" stroke="#6c63ff" stroke-width="1" stroke-linejoin="round"/>
</svg>`

const fs = require('fs')
const path = require('path')

for (const size of [16, 48, 128]) {
  fs.writeFileSync(
    path.join(__dirname, `icon${size}.svg`),
    svgTemplate(size)
  )
  console.log(`Written icon${size}.svg`)
}

console.log('SVG files written. Convert to PNG using your preferred tool.')
console.log('Inkscape: inkscape --export-filename=icon16.png -w 16 icon16.svg')
