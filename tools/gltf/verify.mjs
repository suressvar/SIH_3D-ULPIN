import fs from 'node:fs/promises';
import path from 'node:path';
import {NodeIO} from '@gltf-transform/core';
import {dedup} from '@gltf-transform/functions';
import validator from 'gltf-validator';
const directory=process.argv[2];
if (!directory) throw new Error('Provide asset directory');
const io=new NodeIO();
const reports=[];
for (const name of (await fs.readdir(directory)).filter(n=>n.endsWith('.glb')).sort()) {
  const file=path.join(directory,name);
  const doc=await io.read(file);
  await doc.transform(dedup());
  await io.write(file,doc);
  const bytes=await fs.readFile(file);
  const report=await validator.validateBytes(new Uint8Array(bytes),{uri:name,maxIssues:100});
  reports.push({file:name,errors:report.issues.numErrors,warnings:report.issues.numWarnings,messages:report.issues.messages});
  if(report.issues.numErrors) throw new Error('Invalid GLB: '+name+' '+JSON.stringify(report.issues));
}
await fs.writeFile(path.join(directory,'gltf-validation.json'),JSON.stringify(reports,null,2));
console.log(JSON.stringify({files:reports.length,errors:0}));
