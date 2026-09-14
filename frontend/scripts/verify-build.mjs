// Parse every shipped script without executing it. This catches dependency code
// that a successful framework build can still emit with invalid browser syntax.
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { Script } from "node:vm";
function check(dir) {
  let count = 0;
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) count += check(path);
    else if (entry.name.endsWith(".js")) {
      new Script(readFileSync(path, "utf8"), { filename: path });
      count++;
    }
  }
  return count;
}
const count = check(".next/static/chunks");
new Script(readFileSync("public/cesium/Cesium.js", "utf8"), { filename: "Cesium.js" });
console.log("Parsed " + count + " application chunks and the local Cesium distribution.");
