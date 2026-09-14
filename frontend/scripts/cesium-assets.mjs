import { cpSync, mkdirSync } from "node:fs";
for (const dir of ["Workers", "Assets", "Widgets", "ThirdParty"]) {
  mkdirSync("public/cesium", { recursive: true });
  cpSync("node_modules/cesium/Build/Cesium/" + dir, "public/cesium/" + dir, {
    recursive: true,
  });
}
cpSync("node_modules/cesium/Build/Cesium/Cesium.js", "public/cesium/Cesium.js");
