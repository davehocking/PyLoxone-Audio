// Development-only compiler. The resulting module has no runtime imports.
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
const here=path.dirname(fileURLToPath(import.meta.url));
const require=process.env.FRONTEND_NODE_MODULES?createRequire(path.resolve(process.env.FRONTEND_NODE_MODULES,'esbuild/package.json')):createRequire(import.meta.url);
const {build}=require('esbuild');
const out=process.argv[2]?path.resolve(process.argv[2]):path.join(here,'dist/group-control-card-0.1.5-r13.js');
await build({absWorkingDir:path.resolve(here,'../../..'),entryPoints:[path.join(here,'src/group-control-card.js')],outfile:out,bundle:true,format:'esm',target:'es2022',minify:false,legalComments:'inline'});
console.log(out);
