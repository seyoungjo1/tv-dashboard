// Optional: NODE_PATH=<directory containing playwright-core> node tests/browser_optimize.cjs
const assert=require('node:assert/strict'),fs=require('node:fs'),http=require('node:http'),path=require('node:path');
const {chromium}=require('playwright-core');
(async()=>{
 const stages=new Map([
  ['html','<!doctype html><script src="_index_files/js/tailwind.js"></script><body><div>rendered</div><script>window.exported = `<html><body></body></html>`; window.ready = true;</script></body>'],
  ['tailwind','const s=document.createElement("style");s.textContent=".marker{--tw-test:1;color:red}";document.head.appendChild(s);']
 ]);
 let count=0,preview;
 const server=http.createServer(async(req,res)=>{
  const u=new URL(req.url,'http://localhost');let body,type='application/json';
  if(u.pathname==='/'){body='<!doctype html><script src="/optimize.js"></script>';type='text/html';}
  else if(u.pathname==='/optimize.js'){body=fs.readFileSync(process.env.OPTIMIZE_JS||path.join(__dirname,'../tvrelay/static/optimize.js'));type='text/javascript';}
  else if(u.pathname==='/api/staged'){body=stages.get(u.searchParams.get('id'));type=u.searchParams.get('name').endsWith('.js')?'text/javascript':'text/html';}
  else if(u.pathname==='/api/stage'){const chunks=[];for await(const c of req)chunks.push(c);const id='stage'+count++;stages.set(id,Buffer.concat(chunks).toString());body=JSON.stringify({id});}
  else if(u.pathname==='/api/offline/preview'){const chunks=[];for await(const c of req)chunks.push(c);preview=Object.fromEntries(JSON.parse(Buffer.concat(chunks)).files.map(f=>[f.rel,f.stage]));body=JSON.stringify({token:'test'});}
  else if(u.pathname.startsWith('/pb/test/')){const rel=u.pathname.slice('/pb/test/'.length);body=stages.get(preview[rel]);type=rel.endsWith('.js')?'text/javascript':'text/html';}
  res.writeHead(body===undefined?404:200,{'Content-Type':type+'; charset=utf-8'});res.end(body===undefined?'missing':body);
 });
 let browser;
 try {
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox','--disable-dev-shm-usage']});
  const page=await browser.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:'+server.address().port);
  const result=await page.evaluate(()=>Optimize.run({folder:'_index_files',files:[
   {path:'index.html',rel:'',stage:'html'},
   {path:'_index_files/js/tailwind.js',rel:'js/tailwind.js',stage:'tailwind',url:'https://cdn.tailwindcss.com'}
  ]},{babel:false,images:false}));
  assert.deepEqual(errors,[],'preview must preserve script template strings');
  const css=result.files.find(f=>f.kind==='css');assert(css,'stylesheet must be generated');
  assert(stages.get(css.stage).includes('--tw-test'));assert(!result.files.some(f=>f.stage==='tailwind'));
  console.log('Tailwind preview with embedded HTML template: PASS');
 }finally{if(browser)await browser.close();server.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
