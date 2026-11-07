// Immutable text-glyph/clip oracle against real pinned native header.
export async function run({page,manager,dialog,out,fs,path,assert,results}){
 const records=[];
 for(const [width,height,large,dark] of [[320,740,false,false],[390,844,false,true],[440,900,true,false],[844,390,true,true],[1280,900,true,true]]){
  await page.setViewportSize({width,height});await page.emulateMedia({colorScheme:dark?'dark':'light'});
  await dialog.evaluate((d,large)=>{d.style.setProperty('--ha-font-size-xl',large?'30px':'20px');d.style.fontSize=large?'21px':'14px';},large);
  await page.waitForTimeout(150);
  const data=await dialog.evaluate(d=>{
   const hd=d.shadowRoot.querySelector('ha-dialog'),header=hd.shadowRoot.querySelector('ha-dialog-header'),title=hd.shadowRoot.querySelector('#ha-dialog-title')||d.shadowRoot.querySelector('[slot=headerTitle]');
   const range=document.createRange();range.selectNodeContents(title);const glyph=range.getBoundingClientRect(),box=header.getBoundingClientRect(),body=hd.shadowRoot.querySelector('.body').getBoundingClientRect();
   const clip=header.shadowRoot.querySelector('.header-content').getBoundingClientRect();
   return {glyph:glyph.toJSON(),header:box.toJSON(),body:body.toJSON(),clip:clip.toJSON(),font:getComputedStyle(title).font,margin:getComputedStyle(title).margin,title:title.textContent};
  });records.push({width,height,large,dark,...data});
  await page.screenshot({path:path.join(out,`header-${width}-${height}.png`)});
 }
 fs.writeFileSync(path.join(out,'header-geometry.json'),JSON.stringify(records,null,2));
 assert.ok(records.every(({glyph,header,body,clip})=>glyph.y>=header.y&&glyph.bottom<=header.bottom&&glyph.bottom<=body.y&&glyph.x>=clip.x&&glyph.right<=clip.right&&glyph.y>=clip.y&&glyph.bottom<=clip.bottom),'Audio groups glyphs must fit real native header clip and not overlap body at every viewport/text size');
 results.push('complete native heading glyphs without clipping/overlap across mobile/short/desktop/larger text');
}
